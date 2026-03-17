@echo off
REM NCL YouTube Digest — Daily Pipeline (Windows Task Scheduler)
REM Schedule: schtasks /create /tn "NCL_YouTubeDigest" /tr "C:\dev\NCL\tools\youtube_digest_daily.bat" /sc daily /st 03:00
REM
REM Fetches latest videos from Chris Williamson and Diary of a CEO,
REM stores as NDJSON events in data/youtube_digest.ndjson

cd /d "C:\dev\NCL"
if not exist "data" mkdir data
python tools/youtube_digest.py 2>> data\youtube_digest_errors.log
