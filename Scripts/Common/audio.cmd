@echo off

set "AUDIO_PCM24=-c:a pcm_s24le -ar 48000"
set "AUDIO_PCM32F=-c:a pcm_f32le -ar 48000"

if not defined AUDION_AUDIO_BITRATE set "AUDION_AUDIO_BITRATE=384k"
