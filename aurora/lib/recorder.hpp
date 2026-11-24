#pragma once

#include "webgpu/gpu.hpp"

#include <cstdint>

// The in-app recorder (Android: GameRecorder.java encodes and writes the MP4). Each frame the game's
// picture, before the overlays and at the recording's size, is turned into NV12 by a compute pass and
// read back without stalling; a recorder thread hands it to the video encoder. The game's sound comes
// from the audio output (aurora_recorder_audio).
namespace aurora::recorder {
// Frame worker, before the frame's submit: queues this frame's picture when a recording wants one.
void encode(const wgpu::CommandEncoder& encoder, const webgpu::PresentSource& source) noexcept;
// Frame worker, after the frame's submit: maps what was queued, unmaps what the encoder took.
void after_submit() noexcept;
void shutdown() noexcept;
} // namespace aurora::recorder

// The audio output's callback: `count` interleaved stereo frames as they play. Free when not recording.
extern "C" void aurora_recorder_audio(const int16_t* frames, uint32_t count, uint32_t sampleRate);
