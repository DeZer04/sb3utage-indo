// Auto-generated GX fatal stubs for NSMBW SMNE01 rev 1 (tools/gen_gx_fatal_stubs.py)
#include "hle_stubs.h"
#include "runtime_log.h"

namespace {
[[noreturn]] void HaltGX(uint32_t addr, const char* name) {
    const char* symbol = name ? name : "<unknown GX symbol>";
    RT_LOGF(RT_TAG_GX,
            "unimplemented GX entry point: %s at guest address 0x%08X.\n"
            "[gx] This graphics call has no Aurora implementation bound to it yet, so the\n"
            "[gx] runtime cannot continue without silently dropping GPU state. Bind it in\n"
            "[gx] runtime/src/hle/gx/ and remove the stub from gx_fatal_stubs.cpp.\n",
            symbol, addr);
    std::fflush(stderr);
    char message[512]{};
    std::snprintf(message, sizeof(message),
                  "%s at guest address 0x%08X has no Aurora implementation bound to it, so the "
                  "runtime stopped rather than keep rendering with missing GPU state.",
                  symbol, addr);
    ShowRuntimeFatalPopup("the game called an unimplemented graphics function", message);
    std::abort();
}
} // namespace

// Every fatal stub is the same two statements with the address and the symbol
// name substituted, so the body comes from this macro. The registration is
// deliberately still spelled out per entry so the translator's runtime-native
// index sees the literal PPC_NATIVE_OVERRIDE_VOID invocation. Hiding it inside
// this macro would leave the index unable to associate an address with the stub.
#define GX_FATAL_STUB(addr, sym) \
    extern "C" void gx_stub_##addr(CpuContext* ctx) { (void)ctx; HaltGX(0x##addr, sym); }

GX_FATAL_STUB(8059da10, "__GXShutdown_801c1b10") PPC_NATIVE_OVERRIDE_VOID(8059da10, gx_stub_8059da10, (CpuContext* ctx), (ctx));
GX_FATAL_STUB(8059ea80, "GXCPInterruptHandler_801c2b80") PPC_NATIVE_OVERRIDE_VOID(8059ea80, gx_stub_8059ea80, (CpuContext* ctx), (ctx));
GX_FATAL_STUB(8059f2c0, "__GXCleanGPFifo_801c35c0") PPC_NATIVE_OVERRIDE_VOID(8059f2c0, gx_stub_8059f2c0, (CpuContext* ctx), (ctx));
GX_FATAL_STUB(8059f8e0, "__GXSetVCD_801c3c40") PPC_NATIVE_OVERRIDE_VOID(8059f8e0, gx_stub_8059f8e0, (CpuContext* ctx), (ctx));
GX_FATAL_STUB(8059f990, "__GXCalculateVLim_801c3cf0") PPC_NATIVE_OVERRIDE_VOID(8059f990, gx_stub_8059f990, (CpuContext* ctx), (ctx));
GX_FATAL_STUB(8059FE70, "__GXSetVAT_801c4420") PPC_NATIVE_OVERRIDE_VOID(8059FE70, gx_stub_8059FE70, (CpuContext* ctx), (ctx));
GX_FATAL_STUB(805A02A0, "__GXAbort_801c4b70") PPC_NATIVE_OVERRIDE_VOID(805A02A0, gx_stub_805A02A0, (CpuContext* ctx), (ctx));
GX_FATAL_STUB(805a0df0, "__GXSendFlushPrim_801c56c0") PPC_NATIVE_OVERRIDE_VOID(805a0df0, gx_stub_805a0df0, (CpuContext* ctx), (ctx));
GX_FATAL_STUB(805a4940, "__GXSetProjection_801c97f0") PPC_NATIVE_OVERRIDE_VOID(805a4940, gx_stub_805a4940, (CpuContext* ctx), (ctx));
GX_FATAL_STUB(805A4C50, "__GXSetViewport_801c9b40") PPC_NATIVE_OVERRIDE_VOID(805A4C50, gx_stub_805A4C50, (CpuContext* ctx), (ctx));
GX_FATAL_STUB(805A4E60, "__GXSetMatrixIndex_801c9d90") PPC_NATIVE_OVERRIDE_VOID(805A4E60, gx_stub_805A4E60, (CpuContext* ctx), (ctx));
GX_FATAL_STUB(805a4ef0, "GXSetGPMetric_801c9e20") PPC_NATIVE_OVERRIDE_VOID(805a4ef0, gx_stub_805a4ef0, (CpuContext* ctx), (ctx));
GX_FATAL_STUB(805a5710, "GXClearGPMetric_801ca640") PPC_NATIVE_OVERRIDE_VOID(805a5710, gx_stub_805a5710, (CpuContext* ctx), (ctx));
