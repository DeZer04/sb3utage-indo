#include "gx_thread.hpp"

#include "fifo.hpp"
#include "../internal.hpp"
#include "../webgpu/gpu.hpp"

#include <aurora/aurora.h>

#include <algorithm>
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstdlib>
#include <cstring>
#include <deque>
#include <mutex>
#include <thread>
#include <vector>

#if defined(__linux__)
#include <pthread.h>
#endif
#if defined(__ANDROID__)
#include <cerrno>
#include <sys/resource.h>
#include <unistd.h>
#endif

namespace aurora {
extern std::atomic<AuroraFrameWorkerWaitCallback> g_frameWorkerWaitCallback;
}

namespace aurora::gx::thread {
namespace {
Module Log("aurora::gx::thread");

using Clock = std::chrono::steady_clock;

struct Chunk {
  uint8_t* data = nullptr;
  uint32_t size = 0;
  uint32_t capacity = 0;
};

struct Item {
  Chunk chunk;
  std::function<void()> fn;
  uint64_t fence = 0;
  uint64_t seq = 0; // position in the queue, for stream_mark()
};

struct State {
  std::mutex mutex;
  std::condition_variable cv;     // producer -> GX thread: work queued or stop
  std::condition_variable idleCv; // GX thread -> producer: queue ran empty
  std::deque<Item> queue;
  std::vector<Chunk> freeChunks;
  std::thread thread;
  std::thread::id threadId{};
  bool started = false;
  bool stop = false;
  bool busy = false;
  uint64_t nextFence = 0;
  // Written under the mutex, read without it by fence_reached().
  std::atomic<uint64_t> fenceDone{0};
  // Who sleeps on the condition variables, so a wake-up is only sent when someone waits: a battle
  // frame hands over ~430 chunks, and a futex wake for each was 2.4% of the game thread (Poco X6).
  bool consumerWaiting = false; // the GX thread, in cv.wait
  uint32_t idleWaiters = 0;     // producers in idleCv waits (sync, wait_fence)
};

State g_state;
// A forwarded call running on the producer (BASARA_GX_THREAD=2) owns GX state like the GX thread.
thread_local bool t_runningForwarded = false;

// Every queued item (chunk or closure) is numbered, and the GX thread publishes the number of the
// last one it finished. Items run in order, so "everything up to N has run" is one atomic load: the
// display-list array packing used to queue an empty fenced closure (mutex, closure, chunk hand-over)
// after every list that packed an array, and check slots under the mutex (~2.5% of the game thread
// in a battle, Poco X6).
std::atomic<uint64_t> g_itemsQueued{0}; // written by the producer under the mutex
std::atomic<uint64_t> g_itemsDone{0};

uint64_t next_item_seq_locked() noexcept {
  const uint64_t seq = g_itemsQueued.load(std::memory_order_relaxed) + 1;
  g_itemsQueued.store(seq, std::memory_order_relaxed);
  return seq;
}

std::atomic<uint64_t> g_chunks{0};
std::atomic<uint64_t> g_closures{0};
std::atomic<uint64_t> g_bytes{0};
std::atomic<uint64_t> g_syncs[static_cast<int>(SyncReason::Count)]{};
std::atomic<uint64_t> g_producerWaitNanos{0};
std::atomic<uint64_t> g_gxBusyNanos{0};

void run_item(Item& item) {
  if (item.fn) {
    item.fn();
    item.fn = nullptr;
  } else if (item.chunk.size != 0) {
    fifo::process_chunk(item.chunk.data, item.chunk.size);
  }
}

void thread_main() {
#if defined(__linux__)
  pthread_setname_np(pthread_self(), "GxThread");
#endif
#if defined(__ANDROID__)
  // Half of each frame's draw work: above the app's default priority (nice -4, Android's display
  // level), below the game thread's -10 (runtime cpu_boost.cpp).
  if (setpriority(PRIO_PROCESS, static_cast<id_t>(gettid()), -4) != 0) {
    Log.warn("GX thread priority refused: {}", std::strerror(errno));
  }
#endif
  // Busy time is measured per run of items, from waking up to going idle again, not per item: a
  // battle frame is ~430 chunks, and on Cortex-A76 phones every clock read costs (erratum 1188873
  // traps the counter read), which was 7.7% of this thread on a Redmi (Adreno 618).
  Clock::time_point busySince{};
  bool timing = false;
  for (;;) {
    Item item;
    {
      std::unique_lock lock(g_state.mutex);
      if (g_state.queue.empty()) {
        g_state.busy = false;
        if (timing) {
          timing = false;
          g_gxBusyNanos.fetch_add(
              std::chrono::duration_cast<std::chrono::nanoseconds>(Clock::now() - busySince).count(),
              std::memory_order_relaxed);
        }
        if (g_state.idleWaiters != 0) g_state.idleCv.notify_all();
        g_state.consumerWaiting = true;
        g_state.cv.wait(lock, [] { return g_state.stop || !g_state.queue.empty(); });
        g_state.consumerWaiting = false;
      }
      if (g_state.queue.empty() && g_state.stop) {
        g_state.busy = false;
        g_state.idleCv.notify_all();
        return;
      }
      item = std::move(g_state.queue.front());
      g_state.queue.pop_front();
      g_state.busy = true;
    }
    if (!timing) {
      timing = true;
      busySince = Clock::now();
    }
    try {
      run_item(item);
    } catch (const std::exception& e) {
      Log.error("GX thread item failed: {}", e.what());
    }
    if (item.seq != 0) g_itemsDone.store(item.seq, std::memory_order_release);
    if (item.chunk.data != nullptr) {
      item.chunk.size = 0;
      std::lock_guard lock(g_state.mutex);
      g_state.freeChunks.push_back(item.chunk);
    }
    if (item.fence != 0) {
      bool wake = false;
      {
        std::lock_guard lock(g_state.mutex);
        g_state.fenceDone = item.fence;
        wake = g_state.idleWaiters != 0;
      }
      if (wake) g_state.idleCv.notify_all();
    }
  }
}

// BASARA_GX_THREAD=4 (bisecting): same queue and hand-over points, but no second thread. Items run
// on the producer once BASARA_GX_DEFER_ITEMS are queued (or at a sync/fence), so decode is late
// exactly as with the GX thread, yet nothing runs concurrently.
bool deferred() noexcept {
  static const bool on = [] {
    const char* value = std::getenv("BASARA_GX_THREAD");
    return value != nullptr && value[0] == '4';
  }();
  return on;
}

size_t defer_items() noexcept {
  static const size_t n = [] {
    const char* value = std::getenv("BASARA_GX_DEFER_ITEMS");
    const unsigned long v = value != nullptr ? std::strtoul(value, nullptr, 0) : 0ul;
    return v != 0 ? static_cast<size_t>(v) : size_t{32};
  }();
  return n;
}

bool g_inlineRunning = false; // producer only

// Runs queued items on the calling (producer) thread until the queue is empty or `ticket` is done.
void run_deferred(uint64_t ticket) {
  if (g_inlineRunning) return;
  g_inlineRunning = true;
  for (;;) {
    Item item;
    {
      std::lock_guard lock(g_state.mutex);
      if (g_state.queue.empty() || (ticket != 0 && g_state.fenceDone >= ticket)) break;
      item = std::move(g_state.queue.front());
      g_state.queue.pop_front();
    }
    t_runningForwarded = true;
    try {
      run_item(item);
    } catch (const std::exception& e) {
      Log.error("deferred GX item failed: {}", e.what());
    }
    t_runningForwarded = false;
    if (item.seq != 0) g_itemsDone.store(item.seq, std::memory_order_release);
    std::lock_guard lock(g_state.mutex);
    if (item.chunk.data != nullptr) {
      item.chunk.size = 0;
      g_state.freeChunks.push_back(item.chunk);
    }
    if (item.fence != 0) g_state.fenceDone = item.fence;
  }
  g_inlineRunning = false;
}

void maybe_run_deferred() {
  if (!deferred()) return;
  size_t queued;
  {
    std::lock_guard lock(g_state.mutex);
    queued = g_state.queue.size();
  }
  if (queued >= defer_items()) run_deferred(0);
}

void ensure_started_locked() {
  if (g_state.started) {
    return;
  }
  g_state.started = true;
  g_state.stop = false;
  g_state.busy = false;
  if (deferred()) {
    Log.info("GX thread deferred mode (no thread), {} items", defer_items());
    return;
  }
  g_state.thread = std::thread(thread_main);
  g_state.threadId = g_state.thread.get_id();
  Log.info("GX thread enabled");
}

// Producer only. Swaps the FIFO write buffer for a free one and queues the full one.
void enqueue_pending_bytes_locked() {
  auto& size = fifo::detail::sBufferSize;
  if (size == 0) {
    return;
  }
  Chunk full{fifo::detail::sBufferData, size, fifo::detail::sBufferCapacity};
  Chunk next;
  if (!g_state.freeChunks.empty()) {
    next = g_state.freeChunks.back();
    g_state.freeChunks.pop_back();
  } else {
    next.capacity = full.capacity;
    next.data = static_cast<uint8_t*>(std::malloc(next.capacity));
  }
  fifo::detail::sBufferData = next.data;
  fifo::detail::sBufferCapacity = next.capacity;
  fifo::detail::sBufferSize = 0;
  g_bytes.fetch_add(full.size, std::memory_order_relaxed);
  g_chunks.fetch_add(1, std::memory_order_relaxed);
  g_state.queue.push_back(Item{full, nullptr, 0, next_item_seq_locked()});
}

// Dawn's GL backend has one EGL context; GX work on a second thread fails with EGL_BAD_ACCESS.
bool gl_backend() noexcept {
  return webgpu::g_backendType == wgpu::BackendType::OpenGLES ||
         webgpu::g_backendType == wgpu::BackendType::OpenGL;
}

} // namespace

bool enabled() noexcept {
  // Asked by nearly every GX call (~1% of the game thread in a battle). The answer depends only on
  // the environment and the backend, so it is kept once the backend is known.
  static std::atomic<int> s_known{-1};
  if (const int known = s_known.load(std::memory_order_relaxed); known >= 0) {
    return known != 0;
  }
  static const bool on = [] {
    const char* value = std::getenv("BASARA_GX_THREAD");
    return value != nullptr && (value[0] == '1' || value[0] == '2' || value[0] == '3' || value[0] == '4');
  }();
  const bool backendKnown = webgpu::g_backendType != wgpu::BackendType::Undefined;
  if (on && gl_backend()) {
    static bool logged = false;
    if (!logged) {
      logged = true;
      Log.warn("GX thread off: Dawn's OpenGL ES context can only be current on one thread (EGL_BAD_ACCESS)");
    }
    if (backendKnown) s_known.store(0, std::memory_order_relaxed);
    return false;
  }
  if (backendKnown) s_known.store(on ? 1 : 0, std::memory_order_relaxed);
  return on;
}

namespace {
// BASARA_GX_THREAD=3 (bisecting): everything still runs on the GX thread, but the producer waits
// for it after each hand-over, so nothing the game does next can overlap the decode.
bool lockstep() noexcept {
  static const bool on = [] {
    const char* value = std::getenv("BASARA_GX_THREAD");
    return value != nullptr && value[0] == '3';
  }();
  return on;
}
} // namespace

namespace {
// The bisecting modes that run GX items on the producer (BASARA_GX_THREAD=2 and 4), the only ones
// that set t_runningForwarded.
bool forwards_on_producer() noexcept {
  static const bool on = [] {
    const char* value = std::getenv("BASARA_GX_THREAD");
    return value != nullptr && (value[0] == '2' || value[0] == '4');
  }();
  return on;
}
} // namespace

bool on_gx_thread() noexcept {
  // threadId is written once, before any item can run, under the queue mutex. The thread_local is
  // read only in the modes that set it: in a dlopen'ed library it goes through the dynamic TLS
  // resolver, 1.2% of the game thread when every GX call asked.
  if (g_state.started && std::this_thread::get_id() == g_state.threadId) {
    return true;
  }
  return forwards_on_producer() && t_runningForwarded;
}

void submit() {
  if (!offload() || fifo::detail::sBufferSize == 0) {
    return;
  }
  bool wake = false;
  {
    std::lock_guard lock(g_state.mutex);
    ensure_started_locked();
    enqueue_pending_bytes_locked();
    wake = g_state.consumerWaiting;
  }
  if (wake) g_state.cv.notify_one();
  if (lockstep()) sync(SyncReason::Other);
  maybe_run_deferred();
}

namespace {
uint64_t post_impl(std::function<void()> fn, const char* name, bool fenced) {
  // First use of each forwarded call site (diagnostics, BASARA_GX_THREAD_LOG=1): a mutex and a scan
  // on every forwarded call otherwise.
  static const bool logFirstUse = [] {
    const char* value = std::getenv("BASARA_GX_THREAD_LOG");
    return value != nullptr && value[0] == '1';
  }();
  if (logFirstUse && name != nullptr) {
    static std::mutex seenMutex;
    static std::vector<const char*> seen;
    std::lock_guard lock(seenMutex);
    if (std::find(seen.begin(), seen.end(), name) == seen.end() && seen.size() < 128) {
      seen.push_back(name);
      Log.info("first forwarded call: {}", name);
    }
  }
  // BASARA_GX_THREAD=2 (bisecting): run forwarded calls on the producer after a full sync.
  static const bool inlinePosts = [] {
    const char* value = std::getenv("BASARA_GX_THREAD");
    return value != nullptr && value[0] == '2';
  }();
  if (inlinePosts) {
    sync(SyncReason::Other);
    t_runningForwarded = true;
    fn();
    t_runningForwarded = false;
    return 0;
  }
  uint64_t ticket = 0;
  bool wake = false;
  {
    std::lock_guard lock(g_state.mutex);
    ensure_started_locked();
    enqueue_pending_bytes_locked();
    if (fenced) ticket = ++g_state.nextFence;
    g_state.queue.push_back(Item{{}, std::move(fn), ticket, next_item_seq_locked()});
    g_closures.fetch_add(1, std::memory_order_relaxed);
    wake = g_state.consumerWaiting;
  }
  if (wake) g_state.cv.notify_one();
  if (lockstep()) sync(SyncReason::Other);
  else sync_after(kSyncAfterPost);
  maybe_run_deferred();
  return ticket;
}

unsigned sync_after_mask() noexcept {
  static const unsigned mask = [] {
    const char* value = std::getenv("BASARA_GX_SYNC_AFTER");
    return value != nullptr ? static_cast<unsigned>(std::strtoul(value, nullptr, 0)) : 0u;
  }();
  return mask;
}
} // namespace

void sync_after(unsigned bit) {
  if ((sync_after_mask() & bit) != 0 && offload()) sync(SyncReason::Other);
}

void post(std::function<void()> fn, const char* name) { post_impl(std::move(fn), name, false); }

uint64_t post_fenced(std::function<void()> fn, const char* name) {
  if (!offload()) {
    fn();
    return 0;
  }
  return post_impl(std::move(fn), name, true);
}

bool fence_reached(uint64_t ticket) {
  if (ticket == 0 || !offload()) {
    return true;
  }
  return g_state.fenceDone.load(std::memory_order_acquire) >= ticket;
}

uint64_t stream_mark() noexcept {
  if (!offload()) {
    return 0;
  }
  // The pending FIFO bytes become the next item when they are handed over.
  return g_itemsQueued.load(std::memory_order_relaxed) + (fifo::detail::sBufferSize != 0 ? 1 : 0);
}

bool stream_mark_reached(uint64_t mark) noexcept {
  return mark == 0 || g_itemsDone.load(std::memory_order_acquire) >= mark;
}

void wait_stream_mark(uint64_t mark, SyncReason reason) {
  if (stream_mark_reached(mark)) {
    return;
  }
  // A fence after everything queued so far, pending bytes included, covers the mark.
  wait_fence(post_fenced([] {}, nullptr), reason);
}

void wait_fence(uint64_t ticket, SyncReason reason) {
  if (ticket == 0 || !offload()) {
    return;
  }
  if (deferred()) {
    g_syncs[static_cast<int>(reason)].fetch_add(1, std::memory_order_relaxed);
    run_deferred(ticket);
    return;
  }
  std::unique_lock lock(g_state.mutex);
  if (g_state.fenceDone >= ticket) {
    return;
  }
  g_syncs[static_cast<int>(reason)].fetch_add(1, std::memory_order_relaxed);
  g_state.cv.notify_one();
  const auto started = Clock::now();
  ++g_state.idleWaiters;
  while (g_state.fenceDone < ticket) {
    if (g_state.idleCv.wait_for(lock, std::chrono::milliseconds(1), [ticket] { return g_state.fenceDone >= ticket; })) {
      break;
    }
    // Keep the guest's alarm/retrace pump alive while waiting.
    lock.unlock();
    if (const auto callback = g_frameWorkerWaitCallback.load(std::memory_order_acquire)) {
      callback();
    }
    lock.lock();
  }
  --g_state.idleWaiters;
  g_producerWaitNanos.fetch_add(
      std::chrono::duration_cast<std::chrono::nanoseconds>(Clock::now() - started).count(),
      std::memory_order_relaxed);
}

void sync(SyncReason reason) {
  if (!offload()) {
    return;
  }
  g_syncs[static_cast<int>(reason)].fetch_add(1, std::memory_order_relaxed);
  std::unique_lock lock(g_state.mutex);
  if (!g_state.started) {
    // Nothing ever ran on the GX thread; whatever is pending is still the producer's to decode.
    return;
  }
  enqueue_pending_bytes_locked();
  if (deferred()) {
    lock.unlock();
    run_deferred(0);
    return;
  }
  if (g_state.queue.empty() && !g_state.busy) {
    return;
  }
  g_state.cv.notify_one();
  const auto started = Clock::now();
  ++g_state.idleWaiters;
  while (!g_state.queue.empty() || g_state.busy) {
    if (g_state.idleCv.wait_for(lock, std::chrono::milliseconds(1),
                                [] { return g_state.queue.empty() && !g_state.busy; })) {
      break;
    }
    // Keep the guest's alarm/retrace pump alive, as a producer waiting on the frame worker does.
    lock.unlock();
    if (const auto callback = g_frameWorkerWaitCallback.load(std::memory_order_acquire)) {
      callback();
    }
    lock.lock();
  }
  --g_state.idleWaiters;
  g_producerWaitNanos.fetch_add(
      std::chrono::duration_cast<std::chrono::nanoseconds>(Clock::now() - started).count(),
      std::memory_order_relaxed);
}

Stats take_stats() noexcept {
  Stats s;
  s.chunks = g_chunks.exchange(0, std::memory_order_relaxed);
  s.closures = g_closures.exchange(0, std::memory_order_relaxed);
  s.bytes = g_bytes.exchange(0, std::memory_order_relaxed);
  for (int i = 0; i < static_cast<int>(SyncReason::Count); ++i) {
    s.syncs[i] = g_syncs[i].exchange(0, std::memory_order_relaxed);
  }
  s.producerWaitNanos = g_producerWaitNanos.exchange(0, std::memory_order_relaxed);
  s.gxBusyNanos = g_gxBusyNanos.exchange(0, std::memory_order_relaxed);
  return s;
}

void shutdown() {
  {
    std::lock_guard lock(g_state.mutex);
    if (!g_state.started) {
      return;
    }
    g_state.stop = true;
  }
  g_state.cv.notify_all();
  if (g_state.thread.joinable()) {
    g_state.thread.join();
  }
  std::lock_guard lock(g_state.mutex);
  for (auto& chunk : g_state.freeChunks) {
    std::free(chunk.data);
  }
  g_state.freeChunks.clear();
  g_state.started = false;
}

} // namespace aurora::gx::thread

extern "C" void AuroraTakeGxThreadStats(uint64_t* chunks, uint64_t* closures, uint64_t* bytes, uint64_t* syncs,
                                        uint32_t syncCount, uint64_t* producerWaitNanos, uint64_t* gxBusyNanos) {
  const auto s = aurora::gx::thread::take_stats();
  *chunks = s.chunks;
  *closures = s.closures;
  *bytes = s.bytes;
  for (uint32_t i = 0; i < syncCount && i < static_cast<uint32_t>(aurora::gx::thread::SyncReason::Count); ++i) {
    syncs[i] = s.syncs[i];
  }
  *producerWaitNanos = s.producerWaitNanos;
  *gxBusyNanos = s.gxBusyNanos;
}

extern "C" bool AuroraGxThreadEnabled() { return aurora::gx::thread::enabled(); }

// Fence after everything submitted so far (0 when the GX thread is off: already reached).
extern "C" uint64_t AuroraGxThreadMark() {
  if (!aurora::gx::thread::offload()) return 0;
  return aurora::gx::thread::post_fenced([] {}, nullptr);
}

extern "C" void AuroraGxThreadWaitMark(uint64_t ticket) {
  aurora::gx::thread::wait_fence(ticket, aurora::gx::thread::SyncReason::EndFrame);
}

extern "C" bool AuroraGxThreadMarkReached(uint64_t ticket) {
  return aurora::gx::thread::fence_reached(ticket);
}

// Stream position after everything submitted so far, without queuing a fence (0 when the GX thread
// is off: already reached). It hands the pending bytes over first: the caller marks after each
// display list that packed arrays, and handing over there is what keeps the GX thread decoding
// alongside the game. Left to the 16 KB batches, the two threads took turns (1.0.6-dev1 on the
// Poco X6: same work per frame, 19-24 fps instead of 38-45).
extern "C" uint64_t AuroraGxStreamMark() {
  aurora::gx::thread::submit();
  return aurora::gx::thread::stream_mark();
}

extern "C" bool AuroraGxStreamMarkReached(uint64_t mark) {
  return aurora::gx::thread::stream_mark_reached(mark);
}

extern "C" void AuroraGxWaitStreamMark(uint64_t mark) {
  aurora::gx::thread::wait_stream_mark(mark, aurora::gx::thread::SyncReason::EndFrame);
}

// Run fn(arg) on the GX thread after everything submitted so far, or now when it is off.
extern "C" void AuroraGxThreadPostCall(void (*fn)(uint32_t), uint32_t arg) {
  if (!aurora::gx::thread::offload()) {
    fn(arg);
    return;
  }
  aurora::gx::thread::post([fn, arg] { fn(arg); }, nullptr);
}
