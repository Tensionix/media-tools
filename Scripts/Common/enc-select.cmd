@echo off
rem Usage:
rem   call "%~dp0Common\enc-select.cmd" nvenc
rem   call "%~dp0Common\enc-select.cmd" cpu
setlocal

set "MODE=%~1"
if /I "%MODE%"==""  set "MODE=cpu"

rem ---- probe available hw encoders ----
set "HAS_H264_NVENC="
set "HAS_HEVC_NVENC="
set "HAS_AV1_NVENC="

for /f "delims=" %%E in ('"%FFMPEG%" -hide_banner -encoders ^| findstr /I "h264_nvenc"') do set "HAS_H264_NVENC=1"
for /f "delims=" %%E in ('"%FFMPEG%" -hide_banner -encoders ^| findstr /I "hevc_nvenc"') do set "HAS_HEVC_NVENC=1"
for /f "delims=" %%E in ('"%FFMPEG%" -hide_banner -encoders ^| findstr /I "av1_nvenc"')  do set "HAS_AV1_NVENC=1"

rem ---- defaults (CPU) ----
set "V_H264=-c:v libx264 -pix_fmt yuv420p -preset slow -crf 17"
set "V_HEVC10=-c:v libx265 -pix_fmt yuv420p10le -preset slow -crf 20 -x265-params profile=main10"
set "V_AV1=-c:v libsvtav1 -pix_fmt yuv420p10le -crf 28 -preset 6"
set "ENC_TAG=cpu"

if /I "%MODE%"=="nvenc" (
  rem prefer NVENC when present
  if defined HAS_H264_NVENC (
    set "V_H264=-c:v h264_nvenc -pix_fmt yuv420p -preset p5 -rc constqp -cq 19"
  )
  if defined HAS_HEVC_NVENC (
    set "V_HEVC10=-c:v hevc_nvenc -pix_fmt p010le -profile main10 -preset p5 -rc constqp -cq 19"
  )
  if defined HAS_AV1_NVENC (
    set "V_AV1=-c:v av1_nvenc -pix_fmt p010le -preset p5 -rc constqp -cq 24"
  )
  set "ENC_TAG=nvenc"
)

endlocal & (
  set "V_H264=%V_H264%"
  set "V_HEVC10=%V_HEVC10%"
  set "V_AV1=%V_AV1%"
  set "ENC_TAG=%ENC_TAG%"
)
