// This file was generated with the assistance of an AI coding tool.
// Test-only stand-in so viewer headers parse. The rdbview tests do not call wgpu.
#pragma once
#include <cstdint>

struct WGPUAdapterImpl;
struct WGPUBindGroupImpl;
struct WGPUBindGroupLayoutImpl;
struct WGPUBufferImpl;
struct WGPUCommandEncoderImpl;
struct WGPUDeviceImpl;
struct WGPUInstanceImpl;
struct WGPUPipelineLayoutImpl;
struct WGPUQueueImpl;
struct WGPURenderPassEncoderImpl;
struct WGPURenderPipelineImpl;
struct WGPUSamplerImpl;
struct WGPUShaderModuleImpl;
struct WGPUSurfaceImpl;
struct WGPUTextureImpl;
struct WGPUTextureViewImpl;

using WGPUAdapter = WGPUAdapterImpl*;
using WGPUBindGroup = WGPUBindGroupImpl*;
using WGPUBindGroupLayout = WGPUBindGroupLayoutImpl*;
using WGPUBuffer = WGPUBufferImpl*;
using WGPUCommandEncoder = WGPUCommandEncoderImpl*;
using WGPUDevice = WGPUDeviceImpl*;
using WGPUInstance = WGPUInstanceImpl*;
using WGPUPipelineLayout = WGPUPipelineLayoutImpl*;
using WGPUQueue = WGPUQueueImpl*;
using WGPURenderPassEncoder = WGPURenderPassEncoderImpl*;
using WGPURenderPipeline = WGPURenderPipelineImpl*;
using WGPUSampler = WGPUSamplerImpl*;
using WGPUShaderModule = WGPUShaderModuleImpl*;
using WGPUSurface = WGPUSurfaceImpl*;
using WGPUTexture = WGPUTextureImpl*;
using WGPUTextureView = WGPUTextureViewImpl*;

struct WGPUAdapterInfo { int dummy = 0; };
struct WGPUBufferDescriptor { int dummy = 0; };
struct WGPUSurfaceDescriptor { int dummy = 0; };
struct WGPUSurfaceSourceMetalLayer { int dummy = 0; };
using WGPUBufferUsage = uint32_t;
enum WGPUTextureFormat { WGPUTextureFormat_Undefined = 0 };

inline void wgpuBufferRelease(WGPUBuffer) {}
