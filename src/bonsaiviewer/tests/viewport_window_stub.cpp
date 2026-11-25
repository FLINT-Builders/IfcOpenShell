// This file was generated with the assistance of an AI coding tool.
//
// openProjectPath needs a ViewportWindow to clear the scene. The real
// constructor initialises a wgpu device; these definitions build the same
// object far enough for clearScene's setSelectedObjectId / removeModel /
// setCamera calls and do not create a GPU device.

#include "../../ifcviewer/ViewportWindow.h"

#include "../../ifcviewer/AreaMeasurement.h"
#include "../../ifcviewer/AxisIndicatorRenderer.h"
#include "../../ifcviewer/BufferPool.h"
#include "../../ifcviewer/LengthMeasurement.h"
#include "../../ifcviewer/OverlayRenderer.h"
#include "../../ifcviewer/SectionGizmoRenderer.h"
#include "../../ifcviewer/StreamingThread.h"

ViewportCore::ViewportCore(ViewportHost* host) : host_(host) {}
ViewportCore::~ViewportCore() = default;

BufferPool::~BufferPool() = default;
StreamingThread::~StreamingThread() = default;
// These renderers were never initialised, so there is no GPU resource to release.
AxisIndicatorRenderer::~AxisIndicatorRenderer() = default;
SectionGizmoRenderer::~SectionGizmoRenderer() = default;
OverlayRenderer::~OverlayRenderer() = default;

ViewportWindow::ViewportWindow(QWindow* parent)
    : QWindow(parent),
      core_(this),
      instance_(core_.instance_),
      adapter_(core_.adapter_),
      device_(core_.device_),
      queue_(core_.queue_),
      surface_(core_.surface_),
      surface_format_(core_.surface_format_),
      surface_configured_(core_.surface_configured_),
      main_shader_module_(core_.main_shader_module_),
      frame_bgl_(core_.frame_bgl_),
      model_bgl_(core_.model_bgl_),
      pipeline_layout_(core_.pipeline_layout_),
      main_pipeline_(core_.main_pipeline_),
      main_pipeline_transparent_(core_.main_pipeline_transparent_),
      depth_texture_(core_.depth_texture_),
      depth_view_(core_.depth_view_),
      depth_w_(core_.depth_w_),
      depth_h_(core_.depth_h_),
      msaa_color_texture_(core_.msaa_color_texture_),
      msaa_color_view_(core_.msaa_color_view_),
      msaa_w_(core_.msaa_w_),
      msaa_h_(core_.msaa_h_),
      hiz_shader_module_(core_.hiz_shader_module_),
      hiz_bgl_(core_.hiz_bgl_),
      hiz_pipeline_layout_(core_.hiz_pipeline_layout_),
      hiz_pipeline_(core_.hiz_pipeline_),
      hiz_uniform_buffer_(core_.hiz_uniform_buffer_),
      hiz_bind_group_(core_.hiz_bind_group_),
      hiz_resolve_texture_(core_.hiz_resolve_texture_),
      hiz_resolve_view_(core_.hiz_resolve_view_),
      hiz_resolve_w_(core_.hiz_resolve_w_),
      hiz_resolve_h_(core_.hiz_resolve_h_),
      hiz_padded_bpr_(core_.hiz_padded_bpr_),
      hiz_pyramid_(core_.hiz_pyramid_),
      hiz_mip_offset_(core_.hiz_mip_offset_),
      hiz_mip_w_(core_.hiz_mip_w_),
      hiz_mip_h_(core_.hiz_mip_h_),
      hiz_vp_(core_.hiz_vp_),
      hiz_valid_(core_.hiz_valid_),
      hiz_reject_count_(core_.hiz_reject_count_),
      hiz_trace_budget_(core_.hiz_trace_budget_),
      hiz_enabled_(core_.hiz_enabled_),
      edge_shader_module_(core_.edge_shader_module_),
      edge_bgl_(core_.edge_bgl_),
      edge_pipeline_layout_(core_.edge_pipeline_layout_),
      edge_pipeline_(core_.edge_pipeline_),
      edge_bind_group_(core_.edge_bind_group_),
      edges_enabled_(core_.edges_enabled_),
      pick_pipeline_(core_.pick_pipeline_),
      pool_(core_.pool_),
      streaming_thread_(core_.streaming_thread_),
      streaming_frame_idx_(core_.streaming_frame_idx_),
      models_gpu_(core_.models_gpu_),
      next_session_model_id_(core_.next_session_model_id_),
      next_object_id_(core_.next_object_id_),
      federated_false_origin_meters_(core_.federated_false_origin_meters_),
      wgpu_initialized_(core_.wgpu_initialized_),
      configured_w_(core_.configured_w_),
      configured_h_(core_.configured_h_),
      camera_target_(core_.camera_target_),
      camera_distance_(core_.camera_distance_),
      projection_ortho_(core_.projection_ortho_),
      camera_yaw_deg_(core_.camera_yaw_deg_),
      camera_pitch_deg_(core_.camera_pitch_deg_),
      camera_fov_y_deg_(core_.camera_fov_y_deg_),
      camera_near_(core_.camera_near_),
      camera_far_(core_.camera_far_),
      frame_uniform_buffer_(core_.frame_uniform_buffer_),
      frame_bind_group_(core_.frame_bind_group_),
      selection_flags_buffer_(core_.selection_flags_buffer_),
      selection_flags_capacity_(core_.selection_flags_capacity_),
      selection_flags_scratch_(core_.selection_flags_scratch_),
      section_planes_(core_.section_planes_),
      xray_alpha_cap_(core_.xray_alpha_cap_),
      selection_(core_.selection_),
      visibility_(core_.visibility_),
      tracked_object_id_(core_.tracked_object_id_),
      tracked_chunk_mid_(core_.tracked_chunk_mid_),
      tracked_chunk_idx_(core_.tracked_chunk_idx_),
      tracked_was_resident_(core_.tracked_was_resident_),
      streaming_loads_this_frame_(core_.streaming_loads_this_frame_),
      streaming_more_pending_(core_.streaming_more_pending_),
      streaming_candidates_this_frame_(core_.streaming_candidates_this_frame_),
      streaming_evictions_lru_this_frame_(core_.streaming_evictions_lru_this_frame_),
      streaming_evictions_pri_this_frame_(core_.streaming_evictions_pri_this_frame_),
      streaming_drained_this_frame_(core_.streaming_drained_this_frame_),
      streaming_blocked_oom_this_frame_(core_.streaming_blocked_oom_this_frame_),
      streaming_debug_(core_.streaming_debug_),
      pending_screenshot_path_(core_.pending_screenshot_path_),
      pending_screenshot_quit_(core_.pending_screenshot_quit_),
      lod1_dbg_count_(core_.lod1_dbg_count_),
      lod0_dbg_eligible_count_(core_.lod0_dbg_eligible_count_),
      lod0_dbg_no_lod1_count_(core_.lod0_dbg_no_lod1_count_),
      lod1_dbg_tris_saved_(core_.lod1_dbg_tris_saved_),
      initial_view_applied_(core_.initial_view_applied_),
      min_pixel_radius_(core_.min_pixel_radius_),
      motion_min_pixel_radius_(core_.motion_min_pixel_radius_),
      lod1_pixel_threshold_(core_.lod1_pixel_threshold_),
      cull_threads_enabled_(core_.cull_threads_enabled_),
      prev_camera_target_(core_.prev_camera_target_),
      prev_camera_distance_(core_.prev_camera_distance_),
      prev_camera_yaw_deg_(core_.prev_camera_yaw_deg_),
      prev_camera_pitch_deg_(core_.prev_camera_pitch_deg_),
      has_prev_camera_(core_.has_prev_camera_),
      last_cull_was_motion_(core_.last_cull_was_motion_),
      bench_warm_streak_(core_.bench_warm_streak_),
      bench_warm_frames_total_(core_.bench_warm_frames_total_),
      bench_warm_done_(core_.bench_warm_done_),
      bench_total_(core_.bench_total_),
      bench_count_(core_.bench_count_),
      bench_warmup_(core_.bench_warmup_),
      bench_yaw_start_(core_.bench_yaw_start_),
      bench_yaw_speed_(core_.bench_yaw_speed_),
      bench_frame_ms_(core_.bench_frame_ms_),
      last_visible_objects_(core_.last_visible_objects_),
      last_visible_triangles_(core_.last_visible_triangles_),
      last_sub_draws_(core_.last_sub_draws_),
      bench_cull_ms_total_(core_.bench_cull_ms_total_),
      bench_stream_ms_total_(core_.bench_stream_ms_total_),
      bench_hiz_readback_ms_total_(core_.bench_hiz_readback_ms_total_),
      last_cull_ms_(core_.last_cull_ms_),
      last_cull_compute_ms_(core_.last_cull_compute_ms_),
      last_cull_upload_ms_(core_.last_cull_upload_ms_),
      last_stream_ms_(core_.last_stream_ms_),
      interactive_frame_count_(core_.interactive_frame_count_) {
    setSurfaceType(QSurface::OpenGLSurface);
}

ViewportWindow::~ViewportWindow() = default;

void ViewportWindow::setSelectedObjectId(uint32_t id) {
    if (id == 0) selection_.clear();
    else selection_.replace(id);
}

void ViewportWindow::removeModel(uint32_t) {}

void ViewportWindow::setCamera(float, float, float, float, float, float) {}

WGPUSurface ViewportWindow::createSurface(WGPUInstance) { return nullptr; }
void ViewportWindow::framebufferSize(int& width_px, int& height_px) const {
    width_px = 0;
    height_px = 0;
}
float ViewportWindow::dpr() const { return 1.f; }
void ViewportWindow::requestFrame() {}
void ViewportWindow::quit() {}
void ViewportWindow::onObjectPicked(uint32_t) {}
void ViewportWindow::onSurfacePickedInTool(int, int, int) {}
void ViewportWindow::onToolModeChanged(int) {}
void ViewportWindow::onToolBackspacePressed() {}
void ViewportWindow::onFrameStats(const FrameStats&) {}
void ViewportWindow::encodeOverlaysInMainPass(WGPURenderPassEncoder, const OverlayFrame&) {}
void ViewportWindow::encodeOverlaysPostMain(WGPUCommandEncoder, WGPUTextureView, const OverlayFrame&) {}
void ViewportWindow::saveScreenshotRgba8(const std::string&, const std::uint8_t*, int, int) {}

void ViewportWindow::exposeEvent(QExposeEvent*) {}
void ViewportWindow::resizeEvent(QResizeEvent*) {}
bool ViewportWindow::event(QEvent* event) { return QWindow::event(event); }
void ViewportWindow::mousePressEvent(QMouseEvent*) {}
void ViewportWindow::mouseReleaseEvent(QMouseEvent*) {}
void ViewportWindow::mouseMoveEvent(QMouseEvent*) {}
void ViewportWindow::wheelEvent(QWheelEvent*) {}
void ViewportWindow::keyPressEvent(QKeyEvent*) {}
void ViewportWindow::keyReleaseEvent(QKeyEvent*) {}
