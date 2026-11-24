// disc_import_jni.cpp - the launcher's way into disc_extract (io.github.dezer04.sb3utage.DiscImport).
#include "disc_extract.h"

#include <jni.h>
#include <unistd.h>

#include <cerrno>
#include <memory>
#include <string>
#include <unordered_map>
#include <vector>

namespace {

disc::ReadAt FileReader(int fd) {
    return [fd](uint64_t offset, void* out, size_t size) {
        auto* bytes = static_cast<char*>(out);
        while (size != 0) {
            const ssize_t got = pread64(fd, bytes, size, static_cast<off64_t>(offset));
            if (got < 0 && errno == EINTR) continue;
            if (got <= 0) return false;
            bytes += got;
            offset += static_cast<uint64_t>(got);
            size -= static_cast<size_t>(got);
        }
        return true;
    };
}

// An open game for the patch installer (TlPatch.java): the disc and its files by path, read file by file.
struct OpenGame {
    std::unique_ptr<disc::GameDisc> disc;
    std::unordered_map<std::string, const disc::DiscFile*> files;
};

}  // namespace

extern "C" {

JNIEXPORT jbyteArray JNICALL Java_io_github_dezer04_sb3utage_DiscImport_readHeader(JNIEnv* env, jclass, jint fd) {
    uint8_t header[8];
    std::string message;
    if (!disc::ReadHeader(FileReader(fd), header, message)) {
        env->ThrowNew(env->FindClass("java/io/IOException"), message.c_str());
        return nullptr;
    }
    jbyteArray result = env->NewByteArray(sizeof(header));
    if (result != nullptr) {
        env->SetByteArrayRegion(result, 0, sizeof(header), reinterpret_cast<const jbyte*>(header));
    }
    return result;
}

JNIEXPORT jstring JNICALL Java_io_github_dezer04_sb3utage_DiscImport_extract(JNIEnv* env, jclass, jint fd, jstring outDir,
                                                                       jlong freeBytes, jobject listener) {
    const char* chars = env->GetStringUTFChars(outDir, nullptr);
    const std::string path(chars);
    env->ReleaseStringUTFChars(outDir, chars);
    const jmethodID onProgress = env->GetMethodID(env->GetObjectClass(listener), "onProgress", "(JJ)Z");
    const disc::Result result = disc::Extract(FileReader(fd), path, static_cast<uint64_t>(freeBytes),
        [&](uint64_t done, uint64_t total) {
            return env->CallBooleanMethod(listener, onProgress, static_cast<jlong>(done), static_cast<jlong>(total)) == JNI_TRUE;
        });
    switch (result.status) {
        case disc::Result::Status::Ok: return nullptr;
        case disc::Result::Status::Cancelled: return env->NewStringUTF("");
        default: return env->NewStringUTF(result.message.c_str());
    }
}

JNIEXPORT jlong JNICALL Java_io_github_dezer04_sb3utage_DiscImport_openGame(JNIEnv* env, jclass, jint fd) {
    std::string message;
    auto game = std::make_unique<OpenGame>();
    game->disc = disc::GameDisc::Open(FileReader(fd), message);
    if (!game->disc) {
        env->ThrowNew(env->FindClass("java/io/IOException"), message.c_str());
        return 0;
    }
    for (const disc::DiscFile& file : game->disc->Files()) game->files.emplace(file.path, &file);
    return reinterpret_cast<jlong>(game.release());
}

JNIEXPORT jbyteArray JNICALL Java_io_github_dezer04_sb3utage_DiscImport_readFile(JNIEnv* env, jclass, jlong handle,
                                                                         jstring path) {
    auto* game = reinterpret_cast<OpenGame*>(handle);
    const char* chars = env->GetStringUTFChars(path, nullptr);
    const auto found = game->files.find(chars);
    env->ReleaseStringUTFChars(path, chars);
    if (found == game->files.end()) return nullptr;
    const disc::DiscFile& file = *found->second;
    if (file.size > 0x7fffffffULL) {
        env->ThrowNew(env->FindClass("java/io/IOException"), (file.path + ": too large").c_str());
        return nullptr;
    }
    std::vector<uint8_t> bytes(static_cast<size_t>(file.size));
    std::string error;
    if (!bytes.empty() && !game->disc->Read(file.offset, bytes.data(), bytes.size(), &error)) {
        env->ThrowNew(env->FindClass("java/io/IOException"), (file.path + ": " + error).c_str());
        return nullptr;
    }
    jbyteArray result = env->NewByteArray(static_cast<jsize>(bytes.size()));
    if (result != nullptr) {
        env->SetByteArrayRegion(result, 0, static_cast<jsize>(bytes.size()), reinterpret_cast<const jbyte*>(bytes.data()));
    }
    return result;
}

JNIEXPORT void JNICALL Java_io_github_dezer04_sb3utage_DiscImport_closeGame(JNIEnv*, jclass, jlong handle) {
    delete reinterpret_cast<OpenGame*>(handle);
}

}  // extern "C"
