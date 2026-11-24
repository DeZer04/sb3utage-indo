#include "recorder.hpp"

#include "internal.hpp"
#include "window.hpp"

#include <algorithm>
#include <array>
#include <atomic>
#include <chrono>
#include <cmath>
#include <condition_variable>
#include <cstring>
#include <deque>
#include <mutex>
#include <string_view>
#include <thread>
#include <vector>

#ifdef __ANDROID__
#include <jni.h>
#endif

using namespace std::string_view_literals;

namespace aurora::recorder {
namespace {
Module Log("aurora::recorder");

using webgpu::g_device;
using webgpu::g_queue;

// Readbacks in flight: one being drawn, one mapping, one with the encoder and one spare, so a slow
// encoder drops a frame instead of holding the GPU.
constexpr size_t kSlotCount = 4;
constexpr uint64_t kAudioRingFrames = 1u << 16;  // about 1.4 s at 48 kHz
constexpr uint32_t kAudioChunkFrames = 1024;
// A frame up to this early still counts for its slot: 60 FPS game frames fill a 60 FPS recording.
constexpr int64_t kEarlyNs = 4'000'000;

struct Params {
  uint32_t dstWidth = 0;
  uint32_t dstHeight = 0;
  uint32_t srcWidth = 0;
  uint32_t srcHeight = 0;
};
static_assert(sizeof(Params) == 16);

// The game picture scaled to the recording and written as NV12: the luma rows, then the chroma rows
// (U, V pairs), each byte packed four to a word.
constexpr std::string_view kShader = R"(
struct Params {
    dstSize: vec2u,
    srcSize: vec2u,
};
@group(0) @binding(0) var src: texture_2d<f32>;
@group(0) @binding(1) var<storage, read_write> outBytes: array<u32>;
@group(0) @binding(2) var<uniform> params: Params;
@group(0) @binding(3) var srcSampler: sampler;

// `p` in recording pixels, scaled onto the game picture: one hardware bilinear fetch. Four texel loads
// and the blend in the shader made a 720p frame (with its readback copy) 1.2 ms on an Adreno 710; 0.84 ms now.
fn rgb(p: vec2f) -> vec3f {
    return textureSampleLevel(src, srcSampler, p / vec2f(params.dstSize), 0.0).rgb;
}

// BT.709 in limited range, as the encoder is told.
fn luma(c: vec3f) -> f32 {
    return dot(c, vec3f(0.2126, 0.7152, 0.0722));
}

fn to_byte(v: f32) -> u32 {
    return u32(clamp(v + 0.5, 0.0, 255.0));
}

// One invocation: 4 luma bytes of row y and, in the top half, 2 chroma pairs of chroma row y.
@compute @workgroup_size(8, 8, 1)
fn cs_main(@builtin(global_invocation_id) id: vec3u) {
    let words = params.dstSize.x / 4u;
    if (id.x >= words || id.y >= params.dstSize.y) {
        return;
    }
    var y = 0u;
    for (var i = 0u; i < 4u; i++) {
        let c = rgb(vec2f(f32(id.x * 4u + i) + 0.5, f32(id.y) + 0.5));
        y |= to_byte(16.0 + 219.0 * luma(c)) << (8u * i);
    }
    outBytes[id.y * words + id.x] = y;
    if (id.y < params.dstSize.y / 2u) {
        var uv = 0u;
        for (var i = 0u; i < 2u; i++) {
            // The middle of the 2x2 block the chroma sample stands for.
            let c = rgb(vec2f(f32(id.x * 4u + i * 2u) + 1.0, f32(id.y * 2u) + 1.0));
            let l = luma(c);
            uv |= to_byte(128.0 + 224.0 * (c.b - l) / 1.8556) << (16u * i);
            uv |= to_byte(128.0 + 224.0 * (c.r - l) / 1.5748) << (16u * i + 8u);
        }
        outBytes[words * params.dstSize.y + id.y * words + id.x] = uv;
    }
}
)"sv;

enum class SlotState : uint8_t {
  Free,
  Encoded,  // drawn in this frame's commands
  Mapping,
  Mapped,   // waiting for the recorder thread
  Sent,     // the encoder has it: the frame worker unmaps it
};

struct Slot {
  wgpu::Buffer storage;
  wgpu::Buffer readback;
  wgpu::Buffer params;
  wgpu::BindGroup bindGroup;
  WGPUTexture boundTexture = nullptr;
  Params written{};
  uint32_t width = 0;
  uint32_t height = 0;
  uint64_t bytes = 0;
  int64_t ptsNs = 0;
  const uint8_t* data = nullptr;
  std::atomic<SlotState> state{SlotState::Free};
};

std::array<Slot, kSlotCount> g_slots;
wgpu::BindGroupLayout g_layout;
wgpu::ComputePipeline g_pipeline;
wgpu::Sampler g_sampler;
bool g_failed = false;
uint32_t g_slotWidth = 0;  // the slots' buffers (frame worker)
uint32_t g_slotHeight = 0;

std::atomic<bool> g_active{false};
std::atomic<uint32_t> g_width{0};
std::atomic<uint32_t> g_height{0};
std::atomic<int64_t> g_intervalNs{0};
std::atomic<int64_t> g_startNs{0};
std::atomic<uint32_t> g_generation{0};
uint32_t g_seenGeneration = 0;  // frame worker
int64_t g_nextFrameNs = 0;      // frame worker
std::atomic<float> g_aspect{16.f / 9.f};
std::atomic<uint32_t> g_dropped{0};
std::atomic<uint32_t> g_sent{0};

std::mutex g_mutex;
std::condition_variable g_cv;
std::deque<size_t> g_ready;
bool g_running = false;  // the recorder thread takes frames (g_mutex)
bool g_stop = false;
std::thread g_thread;

std::vector<int16_t> g_ring(kAudioRingFrames * 2);
std::atomic<uint64_t> g_ringHead{0};  // frames written by the audio callback
std::atomic<uint64_t> g_ringTail{0};  // frames taken by the recorder thread
std::atomic<bool> g_audioActive{false};
std::atomic<uint32_t> g_audioRate{0};
std::atomic<int64_t> g_audioBaseNs{-1};
std::atomic<uint64_t> g_audioDropped{0};

int64_t now_ns() noexcept {
  return std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now().time_since_epoch())
      .count();
}

bool ensure_pipeline() {
  if (g_pipeline) return true;
  if (g_failed) return false;
  const wgpu::ShaderSourceWGSL wgslSource{wgpu::ShaderSourceWGSL::Init{
      .code = kShader.data(),
  }};
  const wgpu::ShaderModuleDescriptor moduleDescriptor{
      .nextInChain = &wgslSource,
      .label = "Recorder NV12",
  };
  const auto module = g_device.CreateShaderModule(&moduleDescriptor);
  if (!module) {
    Log.error("Failed to create the recorder shader");
    g_failed = true;
    return false;
  }
  const std::array entries{
      wgpu::BindGroupLayoutEntry{
          .binding = 0,
          .visibility = wgpu::ShaderStage::Compute,
          .texture =
              wgpu::TextureBindingLayout{
                  .sampleType = wgpu::TextureSampleType::Float,
                  .viewDimension = wgpu::TextureViewDimension::e2D,
              },
      },
      wgpu::BindGroupLayoutEntry{
          .binding = 1,
          .visibility = wgpu::ShaderStage::Compute,
          .buffer =
              wgpu::BufferBindingLayout{
                  .type = wgpu::BufferBindingType::Storage,
              },
      },
      wgpu::BindGroupLayoutEntry{
          .binding = 2,
          .visibility = wgpu::ShaderStage::Compute,
          .buffer =
              wgpu::BufferBindingLayout{
                  .type = wgpu::BufferBindingType::Uniform,
                  .minBindingSize = sizeof(Params),
              },
      },
      wgpu::BindGroupLayoutEntry{
          .binding = 3,
          .visibility = wgpu::ShaderStage::Compute,
          .sampler =
              wgpu::SamplerBindingLayout{
                  .type = wgpu::SamplerBindingType::Filtering,
              },
      },
  };
  const wgpu::BindGroupLayoutDescriptor layoutDescriptor{
      .label = "Recorder NV12",
      .entryCount = entries.size(),
      .entries = entries.data(),
  };
  g_layout = g_device.CreateBindGroupLayout(&layoutDescriptor);
  const wgpu::PipelineLayoutDescriptor pipelineLayoutDescriptor{
      .bindGroupLayoutCount = 1,
      .bindGroupLayouts = &g_layout,
  };
  const auto pipelineLayout = g_device.CreatePipelineLayout(&pipelineLayoutDescriptor);
  const wgpu::ComputePipelineDescriptor pipelineDescriptor{
      .label = "Recorder NV12",
      .layout = pipelineLayout,
      .compute =
          wgpu::ComputeState{
              .module = module,
              .entryPoint = "cs_main",
          },
  };
  g_pipeline = g_device.CreateComputePipeline(&pipelineDescriptor);
  const wgpu::SamplerDescriptor samplerDescriptor{
      .label = "Recorder NV12",
      .addressModeU = wgpu::AddressMode::ClampToEdge,
      .addressModeV = wgpu::AddressMode::ClampToEdge,
      .magFilter = wgpu::FilterMode::Linear,
      .minFilter = wgpu::FilterMode::Linear,
  };
  g_sampler = g_device.CreateSampler(&samplerDescriptor);
  if (!g_pipeline || !g_sampler) {
    Log.error("Failed to create the recorder pipeline");
    g_failed = true;
    return false;
  }
  return true;
}

void release_slot(Slot& slot) {
  slot.storage = {};
  slot.readback = {};
  slot.params = {};
  slot.bindGroup = {};
  slot.boundTexture = nullptr;
  slot.written = {};
  slot.data = nullptr;
}

// The slots at the recording's size; only while none is in flight.
bool size_slots(uint32_t width, uint32_t height) {
  if (width == g_slotWidth && height == g_slotHeight) return true;
  for (const auto& slot : g_slots) {
    if (slot.state.load(std::memory_order_acquire) != SlotState::Free) return false;
  }
  const uint64_t bytes = static_cast<uint64_t>(width) * height * 3 / 2;
  for (auto& slot : g_slots) {
    release_slot(slot);
    const wgpu::BufferDescriptor storageDescriptor{
        .label = "Recorder frame",
        .usage = wgpu::BufferUsage::Storage | wgpu::BufferUsage::CopySrc,
        .size = bytes,
    };
    slot.storage = g_device.CreateBuffer(&storageDescriptor);
    const wgpu::BufferDescriptor readbackDescriptor{
        .label = "Recorder readback",
        .usage = wgpu::BufferUsage::MapRead | wgpu::BufferUsage::CopyDst,
        .size = bytes,
    };
    slot.readback = g_device.CreateBuffer(&readbackDescriptor);
    const wgpu::BufferDescriptor paramsDescriptor{
        .label = "Recorder params",
        .usage = wgpu::BufferUsage::Uniform | wgpu::BufferUsage::CopyDst,
        .size = sizeof(Params),
    };
    slot.params = g_device.CreateBuffer(&paramsDescriptor);
    slot.width = width;
    slot.height = height;
    slot.bytes = bytes;
  }
  g_slotWidth = width;
  g_slotHeight = height;
  return true;
}

void mapped(size_t index, wgpu::MapAsyncStatus status, wgpu::StringView message) {
  auto& slot = g_slots[index];
  if (status != wgpu::MapAsyncStatus::Success) {
    if (status != wgpu::MapAsyncStatus::CallbackCancelled && status != wgpu::MapAsyncStatus::Aborted) {
      Log.warn("Recorder readback failed: {}", message);
    }
    slot.state.store(SlotState::Free, std::memory_order_release);
    return;
  }
  slot.data = static_cast<const uint8_t*>(slot.readback.GetConstMappedRange(0, slot.bytes));
  std::lock_guard lock{g_mutex};
  if (!g_running || g_stop || slot.data == nullptr) {
    slot.state.store(SlotState::Sent, std::memory_order_release);
    return;
  }
  slot.state.store(SlotState::Mapped, std::memory_order_release);
  g_ready.push_back(index);
  g_cv.notify_one();
}

void push_audio(const int16_t* frames, uint32_t count, uint32_t sampleRate) noexcept {
  if (g_audioRate.load(std::memory_order_relaxed) != sampleRate) {
    g_audioRate.store(sampleRate, std::memory_order_relaxed);
  }
  if (!g_audioActive.load(std::memory_order_acquire) || frames == nullptr || count == 0) return;
  if (g_audioBaseNs.load(std::memory_order_relaxed) < 0) {
    g_audioBaseNs.store(now_ns() - g_startNs.load(std::memory_order_acquire), std::memory_order_release);
  }
  const uint64_t head = g_ringHead.load(std::memory_order_relaxed);
  const uint64_t tail = g_ringTail.load(std::memory_order_acquire);
  const uint64_t room = kAudioRingFrames - (head - tail);
  const uint64_t n = std::min<uint64_t>(count, room);
  if (n < count) g_audioDropped.fetch_add(count - n, std::memory_order_relaxed);
  const uint64_t at = head % kAudioRingFrames;
  const uint64_t first = std::min(n, kAudioRingFrames - at);
  std::memcpy(g_ring.data() + at * 2, frames, first * 2 * sizeof(int16_t));
  if (n > first) std::memcpy(g_ring.data(), frames + first * 2, (n - first) * 2 * sizeof(int16_t));
  g_ringHead.store(head + n, std::memory_order_release);
}

#ifdef __ANDROID__
JavaVM* g_vm = nullptr;
jclass g_class = nullptr;
jmethodID g_onVideo = nullptr;
jmethodID g_onAudio = nullptr;
thread_local const Slot* t_slot = nullptr;

void clear_exception(JNIEnv* env) {
  if (env->ExceptionCheck()) {
    env->ExceptionDescribe();
    env->ExceptionClear();
  }
}

// The recorder thread: frames to GameRecorder.onVideoFrame (which fills the encoder's image through
// nativeFillImage), the audio in 1024-frame blocks to GameRecorder.onAudio.
void run() {
  JNIEnv* env = nullptr;
  JavaVMAttachArgs args{JNI_VERSION_1_6, "SB3 recorder", nullptr};
  if (g_vm->AttachCurrentThread(&env, &args) != JNI_OK) {
    Log.error("Recorder thread could not attach to Java");
    return;
  }
  std::vector<int16_t> chunk(kAudioChunkFrames * 2);
  jobject chunkBuffer = env->NewDirectByteBuffer(chunk.data(), static_cast<jlong>(chunk.size() * sizeof(int16_t)));
  uint64_t audioSent = 0;
  while (true) {
    size_t index = SIZE_MAX;
    bool stop = false;
    {
      std::unique_lock lock{g_mutex};
      g_cv.wait_for(lock, std::chrono::milliseconds{10}, [] { return g_stop || !g_ready.empty(); });
      stop = g_stop;
      if (!g_ready.empty()) {
        index = g_ready.front();
        g_ready.pop_front();
      }
    }
    if (index != SIZE_MAX) {
      auto& slot = g_slots[index];
      if (!stop) {
        t_slot = &slot;
        env->CallStaticVoidMethod(g_class, g_onVideo, static_cast<jlong>(slot.ptsNs / 1000));
        clear_exception(env);
        t_slot = nullptr;
        g_sent.fetch_add(1, std::memory_order_relaxed);
      }
      slot.state.store(SlotState::Sent, std::memory_order_release);
    }
    const uint32_t rate = g_audioRate.load(std::memory_order_relaxed);
    while (!stop && rate != 0) {
      const uint64_t head = g_ringHead.load(std::memory_order_acquire);
      const uint64_t tail = g_ringTail.load(std::memory_order_relaxed);
      if (head - tail < kAudioChunkFrames) break;
      const uint64_t at = tail % kAudioRingFrames;
      const uint64_t first = std::min<uint64_t>(kAudioChunkFrames, kAudioRingFrames - at);
      std::memcpy(chunk.data(), g_ring.data() + at * 2, first * 2 * sizeof(int16_t));
      if (first < kAudioChunkFrames) {
        std::memcpy(chunk.data() + first * 2, g_ring.data(), (kAudioChunkFrames - first) * 2 * sizeof(int16_t));
      }
      g_ringTail.store(tail + kAudioChunkFrames, std::memory_order_release);
      const int64_t ptsNs = g_audioBaseNs.load(std::memory_order_acquire) +
                            static_cast<int64_t>(audioSent * 1'000'000'000ull / rate);
      env->CallStaticVoidMethod(g_class, g_onAudio, chunkBuffer, static_cast<jint>(kAudioChunkFrames * 4),
                                static_cast<jlong>(ptsNs / 1000), static_cast<jint>(rate));
      clear_exception(env);
      audioSent += kAudioChunkFrames;
    }
    if (stop) break;
  }
  {
    // Frames mapped meanwhile go back unsent.
    std::lock_guard lock{g_mutex};
    for (const size_t index : g_ready) g_slots[index].state.store(SlotState::Sent, std::memory_order_release);
    g_ready.clear();
  }
  env->DeleteLocalRef(chunkBuffer);
  g_vm->DetachCurrentThread();
}
#endif

void stop_thread() {
  {
    std::lock_guard lock{g_mutex};
    if (!g_running) return;
    g_stop = true;
    g_cv.notify_all();
  }
  if (g_thread.joinable()) g_thread.join();
  std::lock_guard lock{g_mutex};
  g_running = false;
}
} // namespace

void encode(const wgpu::CommandEncoder& encoder, const webgpu::PresentSource& source) noexcept {
  if (source.size.width == 0 || source.size.height == 0) return;
  float aspect = 0.f;
  if (!window::get_present_aspect_ratio(aspect) || aspect <= 0.f) {
    aspect = static_cast<float>(source.size.width) / static_cast<float>(source.size.height);
  }
  g_aspect.store(aspect, std::memory_order_relaxed);
  if (!g_active.load(std::memory_order_acquire) || !source.texture) return;
  const uint32_t generation = g_generation.load(std::memory_order_acquire);
  if (generation != g_seenGeneration) {
    g_seenGeneration = generation;
    g_nextFrameNs = 0;
  }
  const int64_t now = now_ns();
  if (now + kEarlyNs < g_nextFrameNs) return;
  const uint32_t width = g_width.load(std::memory_order_acquire);
  const uint32_t height = g_height.load(std::memory_order_acquire);
  if (width == 0 || height == 0 || !ensure_pipeline() || !size_slots(width, height)) return;
  Slot* slot = nullptr;
  for (auto& candidate : g_slots) {
    if (candidate.state.load(std::memory_order_acquire) == SlotState::Free) {
      slot = &candidate;
      break;
    }
  }
  if (slot == nullptr) {
    g_dropped.fetch_add(1, std::memory_order_relaxed);
    return;
  }
  const Params params{width, height, source.size.width, source.size.height};
  if (std::memcmp(&params, &slot->written, sizeof(Params)) != 0) {
    g_queue.WriteBuffer(slot->params, 0, &params, sizeof(Params));
    slot->written = params;
  }
  if (!slot->bindGroup || slot->boundTexture != source.texture.Get()) {
    const std::array entries{
        wgpu::BindGroupEntry{
            .binding = 0,
            .textureView = source.texture.CreateView(),
        },
        wgpu::BindGroupEntry{
            .binding = 1,
            .buffer = slot->storage,
            .size = slot->bytes,
        },
        wgpu::BindGroupEntry{
            .binding = 2,
            .buffer = slot->params,
            .size = sizeof(Params),
        },
        wgpu::BindGroupEntry{
            .binding = 3,
            .sampler = g_sampler,
        },
    };
    const wgpu::BindGroupDescriptor descriptor{
        .label = "Recorder NV12",
        .layout = g_layout,
        .entryCount = entries.size(),
        .entries = entries.data(),
    };
    slot->bindGroup = g_device.CreateBindGroup(&descriptor);
    slot->boundTexture = source.texture.Get();
  }
  const wgpu::ComputePassDescriptor passDescriptor{
      .label = "Recorder NV12",
  };
  const auto pass = encoder.BeginComputePass(&passDescriptor);
  pass.SetPipeline(g_pipeline);
  pass.SetBindGroup(0, slot->bindGroup);
  pass.DispatchWorkgroups((width / 4 + 7) / 8, (height + 7) / 8);
  pass.End();
  encoder.CopyBufferToBuffer(slot->storage, 0, slot->readback, 0, slot->bytes);
  slot->ptsNs = now - g_startNs.load(std::memory_order_acquire);
  slot->state.store(SlotState::Encoded, std::memory_order_release);
  const int64_t interval = g_intervalNs.load(std::memory_order_relaxed);
  g_nextFrameNs = now - g_nextFrameNs > interval ? now + interval : g_nextFrameNs + interval;
}

void after_submit() noexcept {
  bool idle = true;
  for (size_t i = 0; i < g_slots.size(); ++i) {
    auto& slot = g_slots[i];
    const auto state = slot.state.load(std::memory_order_acquire);
    if (state == SlotState::Encoded) {
      slot.state.store(SlotState::Mapping, std::memory_order_release);
      slot.readback.MapAsync(wgpu::MapMode::Read, 0, slot.bytes, wgpu::CallbackMode::AllowSpontaneous,
                             [i](wgpu::MapAsyncStatus status, wgpu::StringView message) { mapped(i, status, message); });
      idle = false;
    } else if (state == SlotState::Sent) {
      slot.readback.Unmap();
      slot.data = nullptr;
      slot.state.store(SlotState::Free, std::memory_order_release);
    } else if (state != SlotState::Free) {
      idle = false;
    }
  }
  // A finished recording gives its buffers back.
  if (idle && g_slotWidth != 0 && !g_active.load(std::memory_order_acquire)) {
    for (auto& slot : g_slots) release_slot(slot);
    g_slotWidth = 0;
    g_slotHeight = 0;
  }
}

void shutdown() noexcept {
  g_active.store(false, std::memory_order_release);
  g_audioActive.store(false, std::memory_order_release);
  stop_thread();
  for (auto& slot : g_slots) {
    release_slot(slot);
    slot.state.store(SlotState::Free, std::memory_order_relaxed);
  }
  g_slotWidth = 0;
  g_slotHeight = 0;
  g_pipeline = {};
  g_sampler = {};
  g_layout = {};
  g_failed = false;
}
} // namespace aurora::recorder

extern "C" void aurora_recorder_audio(const int16_t* frames, uint32_t count, uint32_t sampleRate) {
  aurora::recorder::push_audio(frames, count, sampleRate);
}

#ifdef __ANDROID__
using namespace aurora::recorder;

// The recording's size for `height` lines: the picture's shape as the screen shows it, width a
// multiple of 16. (width << 32) | height.
extern "C" JNIEXPORT jlong JNICALL Java_io_github_dezer04_sb3utage_GameRecorder_nativeFrameSize(JNIEnv*, jclass,
                                                                                                 jint lines) {
  const uint32_t height = static_cast<uint32_t>(std::clamp(lines, 240, 2160)) & ~1u;
  const float aspect = std::clamp(g_aspect.load(std::memory_order_relaxed), 1.f, 3.f);
  const uint32_t width = std::max(16u, static_cast<uint32_t>(std::lround(height * aspect / 16.f)) * 16u);
  return (static_cast<jlong>(width) << 32) | height;
}

extern "C" JNIEXPORT jboolean JNICALL Java_io_github_dezer04_sb3utage_GameRecorder_nativeStart(JNIEnv* env, jclass cls,
                                                                                               jint width, jint height,
                                                                                               jint fps) {
  if (width <= 0 || height <= 0 || width % 4 != 0 || height % 2 != 0 || fps <= 0) return JNI_FALSE;
  stop_thread();
  if (g_class != nullptr) {
    env->DeleteGlobalRef(g_class);
    g_class = nullptr;
  }
  env->GetJavaVM(&g_vm);
  g_class = static_cast<jclass>(env->NewGlobalRef(cls));
  g_onVideo = env->GetStaticMethodID(cls, "onVideoFrame", "(J)V");
  g_onAudio = env->GetStaticMethodID(cls, "onAudio", "(Ljava/nio/ByteBuffer;IJI)V");
  if (g_onVideo == nullptr || g_onAudio == nullptr) {
    clear_exception(env);
    return JNI_FALSE;
  }
  g_width.store(static_cast<uint32_t>(width), std::memory_order_release);
  g_height.store(static_cast<uint32_t>(height), std::memory_order_release);
  g_intervalNs.store(1'000'000'000 / fps, std::memory_order_relaxed);
  g_dropped.store(0, std::memory_order_relaxed);
  g_sent.store(0, std::memory_order_relaxed);
  g_audioDropped.store(0, std::memory_order_relaxed);
  g_ringHead.store(0, std::memory_order_relaxed);
  g_ringTail.store(0, std::memory_order_relaxed);
  g_audioBaseNs.store(-1, std::memory_order_relaxed);
  g_startNs.store(now_ns(), std::memory_order_release);
  {
    std::lock_guard lock{g_mutex};
    g_stop = false;
    g_running = true;
    g_ready.clear();
  }
  g_thread = std::thread{run};
  g_generation.fetch_add(1, std::memory_order_release);
  g_audioActive.store(true, std::memory_order_release);
  g_active.store(true, std::memory_order_release);
  Log.info("Recording {}x{} at up to {} FPS", width, height, fps);
  return JNI_TRUE;
}

extern "C" JNIEXPORT void JNICALL Java_io_github_dezer04_sb3utage_GameRecorder_nativeStop(JNIEnv* env, jclass) {
  g_active.store(false, std::memory_order_release);
  g_audioActive.store(false, std::memory_order_release);
  stop_thread();
  if (g_class != nullptr) {
    env->DeleteGlobalRef(g_class);
    g_class = nullptr;
  }
  Log.info("Recording stopped: {} frames, {} dropped, {} audio frames dropped", g_sent.load(), g_dropped.load(),
           g_audioDropped.load());
}

// From onVideoFrame on the recorder thread: the frame into the encoder's image planes (NV12, NV21 or
// planar, whatever the encoder gave).
extern "C" JNIEXPORT jboolean JNICALL Java_io_github_dezer04_sb3utage_GameRecorder_nativeFillImage(
    JNIEnv* env, jclass, jobject yBuffer, jint yRowStride, jobject uBuffer, jobject vBuffer, jint uvRowStride,
    jint uvPixelStride) {
  const Slot* slot = t_slot;
  if (slot == nullptr || slot->data == nullptr) return JNI_FALSE;
  auto* y = static_cast<uint8_t*>(env->GetDirectBufferAddress(yBuffer));
  auto* u = static_cast<uint8_t*>(env->GetDirectBufferAddress(uBuffer));
  auto* v = static_cast<uint8_t*>(env->GetDirectBufferAddress(vBuffer));
  if (y == nullptr || u == nullptr || v == nullptr) return JNI_FALSE;
  const int64_t w = slot->width;
  const int64_t h = slot->height;
  const int64_t cw = w / 2;
  const int64_t ch = h / 2;
  if (env->GetDirectBufferCapacity(yBuffer) < (h - 1) * yRowStride + w ||
      env->GetDirectBufferCapacity(uBuffer) < (ch - 1) * uvRowStride + (cw - 1) * uvPixelStride + 1 ||
      env->GetDirectBufferCapacity(vBuffer) < (ch - 1) * uvRowStride + (cw - 1) * uvPixelStride + 1) {
    return JNI_FALSE;
  }
  const uint8_t* srcY = slot->data;
  const uint8_t* srcUV = slot->data + w * h;
  for (int64_t row = 0; row < h; ++row) {
    std::memcpy(y + row * yRowStride, srcY + row * w, static_cast<size_t>(w));
  }
  if (uvPixelStride == 2 && v == u + 1) {
    for (int64_t row = 0; row < ch; ++row) {
      std::memcpy(u + row * uvRowStride, srcUV + row * w, static_cast<size_t>(w));
    }
  } else if (uvPixelStride == 2 && u == v + 1) {
    for (int64_t row = 0; row < ch; ++row) {
      uint8_t* out = v + row * uvRowStride;
      const uint8_t* in = srcUV + row * w;
      for (int64_t k = 0; k < cw; ++k) {
        out[2 * k] = in[2 * k + 1];
        out[2 * k + 1] = in[2 * k];
      }
    }
  } else {
    for (int64_t row = 0; row < ch; ++row) {
      const uint8_t* in = srcUV + row * w;
      for (int64_t k = 0; k < cw; ++k) {
        u[row * uvRowStride + k * uvPixelStride] = in[2 * k];
        v[row * uvRowStride + k * uvPixelStride] = in[2 * k + 1];
      }
    }
  }
  return JNI_TRUE;
}
#endif
