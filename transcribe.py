import glob
import json
import os
import re
import shlex
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path

import pathvalidate
import pinyin
import pysrt
import speech_recognition as sr
import translators

from gooey import Gooey, GooeyParser

MEDIA_DIR = "./downloads"
SUBTITLE_DIR = "./downloads/subs"


@Gooey(program_name="Subtitle Translator")
def main():
    global MEDIA_DIR
    global SUBTITLE_DIR

    parser = GooeyParser(description="Translate Chinese Subtitles")

    parser.add_argument(
        "media_dir",
        metavar="Media Directory",
        action="store",
        default=MEDIA_DIR,
        help="Directory containing media files",
    )

    parser.add_argument(
        "subtitle_dir",
        metavar="Subtitle Directory",
        action="store",
        default=SUBTITLE_DIR,
        help="Directory to store subtitle files",
    )

    args = parser.parse_args()

    MEDIA_DIR = args.media_dir
    SUBTITLE_DIR = args.subtitle_dir

    os.makedirs(SUBTITLE_DIR, exist_ok=True)

    while True:
        transcribe_media(5)
        translate_zh_subs(0)


def translate_zh_subs(WAITING_NEW_FILE=5):
    sub_files = []

    sub_eng = ""
    sub_vie = ""
    sub_zho = ""
    sub_pin = ""
    sub_all = ""

    patterns = f"{SUBTITLE_DIR}/*.zh.srt"
    for file in glob.glob(patterns):
        sub_zho = file
        path, filename = os.path.split(sub_zho)
        outpath = path

        base_name = filename.split(".zh.srt")[0]
        sub_eng = os.path.join(outpath, base_name + ".en.srt")
        sub_vie = os.path.join(outpath, base_name + ".vi.srt")
        sub_zho = os.path.join(outpath, base_name + ".zh.srt")
        sub_pin = os.path.join(outpath, base_name + ".py.srt")
        sub_all = os.path.join(outpath, base_name + ".srt")

        if not (
            os.path.exists(sub_eng)
            and os.path.exists(sub_vie)
            and os.path.exists(sub_pin)
        ):
            sub_files.append(sub_zho)
            break

    if not sub_files:
        time.sleep(WAITING_NEW_FILE)
        return

    NO_SUBTILE_TEXT = "^[0-9\n\r]"
    print(f"Start translating {sub_zho}...")
    with open(sub_zho, "r", encoding="utf-8") as file_zh:
        text_zh = file_zh.readlines()

        text_all = text_zh.copy()
        text_pin = text_zh.copy()
        text_eng = text_zh.copy()
        text_vie = text_zh.copy()

        count = 1
        MAX_TRANS = 50
        SLEEP_ONE = 1
        SLEEP_BATCH = 60
        SEPERATOR = "\n"

        index_translate = []
        text_translate = []

        for i, line in enumerate(text_zh):
            if not re.match(NO_SUBTILE_TEXT, line):
                index_translate.append(i)
                text_translate.append(line)

        NORMAL_MAX_TRANS = 100
        COMBINED_TRANS = NORMAL_MAX_TRANS

        TEXT_ITEMS = len(text_translate)
        batches = round((TEXT_ITEMS / NORMAL_MAX_TRANS * 1.0) + 0.5)
        remaining = len(text_translate)

        for b in range(batches):
            text_range = text_translate[
                b * NORMAL_MAX_TRANS : (b + 1) * NORMAL_MAX_TRANS
            ]
            index_range = index_translate[
                b * NORMAL_MAX_TRANS : (b + 1) * NORMAL_MAX_TRANS
            ]
            length = len(text_range)

            combined_text = "".join(text_range)

            error_count = 0
            sleep = SLEEP_BATCH
            sleep_one = SLEEP_ONE

            while error_count < 5:
                try:
                    eng = translators.translate_text(
                        combined_text,
                        translator="baidu",
                        from_language="zh",
                        to_language="en",
                    )
                    expanded_eng = eng.split(SEPERATOR)
                    print(f"Sleeping {sleep_one}s")
                    time.sleep(sleep_one)
                    vie = translators.translate_text(
                        combined_text,
                        translator="baidu",
                        from_language="zh",
                        to_language="vie",
                    )
                    expanded_vie = vie.split(SEPERATOR)
                    pin = pinyin.get(combined_text, delimiter=" ")
                    expanded_pin = pin.split(SEPERATOR)

                    break
                except Exception as ex:
                    print(ex)
                    error_count += 1
                    print(f"Sleeping {sleep}s")
                    time.sleep(sleep)

                    sleep = sleep * 1.5
                    sleep_one = sleep * 1.5

            count = 0
            for x in range(min(NORMAL_MAX_TRANS, TEXT_ITEMS - b * NORMAL_MAX_TRANS)):
                y = index_translate[b * NORMAL_MAX_TRANS + x]
                text_eng[y] = expanded_eng[count] + "\n"
                text_vie[y] = expanded_vie[count] + "\n"
                text_pin[y] = expanded_pin[count].strip() + "\n"
                text_all[y] = text_zh[y] + text_pin[y] + text_vie[y]
                count += 1

        with open(sub_eng, "w", encoding="utf-8") as file:
            file.write("".join(text_eng))

        with open(sub_vie, "w", encoding="utf-8") as file:
            file.write("".join(text_vie))

        with open(sub_pin, "w", encoding="utf-8") as file:
            file.write("".join(text_pin))

        with open(sub_all, "w", encoding="utf-8") as file:
            file.write("".join(text_all))

        print(f"Combined file written {sub_all}")
        print(f"Waiting for new subtitle files in {SUBTITLE_DIR}...")

    if not sub_files:
        for file in glob.glob(f"{SUBTITLE_DIR}*.zh.srt"):
            sub_files.append(file)

        sub_files.sort(reverse=True)

        if not sub_files:
            return


def movie_resolution(input_file):
    cmds = f"ffprobe -v error -select_streams v:0 -show_entries stream=width,height -of csv=s=x:p=0 -print_format json -i".split(
        " "
    )
    cmds.append(f"{input_file}")
    metadata = subprocess.check_output(cmds)

    metadata = json.loads(metadata)
    stream0 = metadata["streams"][0]
    width, height = stream0["width"], stream0["height"]

    return width, height


import requests
from pytube import YouTube


def clean_filename(name):
    return re.sub(r"[^a-zA-Z0-9_\- .]", "", name)


def download_file(url, filename):
    response = requests.get(url, stream=True)
    with open(filename, "wb") as file:
        for chunk in response.iter_content(chunk_size=8192):
            file.write(chunk)


def download_youtube_video(url):
    yt = YouTube(url)
    stream = yt.streams.filter(res="720p", file_extension="mp4").first()
    if stream:
        filename = clean_filename(yt.title) + ".mp4"
        stream.download(filename=filename)
        return True
    else:
        print(f"720p video not available for {url}")
        return False


def process_urls(file_path):
    with open(file_path, "r") as file:
        lines = file.readlines()

    if lines[0].startswith("#"):
        urls = lines[1:]
    else:
        urls = lines

    remaining_urls = []

    for line in urls:
        url = line.strip()
        if not url:
            continue

        print(f"Downloading {url}...")

        try:
            if "youtube.com" in url or "youtu.be" in url:
                success = download_youtube_video(url)
            else:
                filename = os.path.basename(url)
                filename = clean_filename(filename)
                download_file(url, filename)
                success = True

            if not success:
                remaining_urls.append(line)
        except Exception as e:
            print(f"Failed to download {url}: {e}")
            remaining_urls.append(line)

    with open(file_path, "w") as file:
        if lines[0].startswith("#"):
            file.write(lines[0])
        for url in remaining_urls:
            file.write(url + "\n")


def movie_duration(input_file):
    cmds = f"ffprobe -v quiet -print_format json -show_format -hide_banner -i".split(
        " "
    )
    cmds.append(f"{input_file}")
    metadata = subprocess.check_output(cmds)

    metadata = json.loads(metadata)
    length = float(metadata["format"]["duration"])

    return length


def convert_media(input, output):
    if input == output:
        print(f"Input and output are the same: {input}")
        return False

    cmd_str = f'ffmpeg -v quiet -y -i "{input}" "{output}"'

    os.system(cmd_str)
    return True


def transcribe_media(WAITING_NEW_FILE=5):
    media_files = []

    process_urls(f"{MEDIA_DIR}/urls.txt")

    for media_file in (
        glob.glob(f"{MEDIA_DIR}/*.mp4")
        + glob.glob(f"{MEDIA_DIR}/*.mp3")
        + glob.glob(f"{MEDIA_DIR}/*.m4a")
        + glob.glob(f"{MEDIA_DIR}/*.wav")
    ):
        if not pathvalidate.is_valid_filepath(media_file):
            new_media_file = pathvalidate.sanitize_filepath(media_file)
            new_media_file = new_media_file.replace(" ", "_")
            try:
                shutil.move(media_file, new_media_file)
                media_file = new_media_file
            except Exception as ex:
                print(ex)

        media_files.append(media_file)

    if not media_files:
        time.sleep(WAITING_NEW_FILE)
        return

    media_file = media_files.pop()

    print(f"Start processing {media_file}...")

    outpath = SUBTITLE_DIR
    video_length = movie_duration(media_file)
    path, filename = os.path.split(media_file)
    base_name, extension = os.path.splitext(filename)
    base_path = os.path.join(outpath, base_name)
    new_media_file = os.path.join(outpath, base_name) + extension

    audio_file = base_path + ".wav"
    mp3_file = base_path + ".mp3"
    sub_zho = base_path + ".zh.srt"
    txt_sub = base_path + ".txt"

    no_text = "^[0-9\n\r]"

    convert_media(media_file, audio_file)
    convert_media(media_file, mp3_file)

    print(f"Audio file exported {audio_file}")

    r = sr.Recognizer()

    with sr.AudioFile(audio_file) as source:
        audio_text = r.record(source)

    translations = [False]
    languages = ["zh"]
    sub_files = [sub_zho]

    print(f"Starting transcribing {audio_file}...")

    start = time.time()

    result = r.recognize_whisper(audio_text, show_dict=True, word_timestamps=True)
    os.remove(audio_file)
    end = time.time()

    print(
        f"Time elapsed {end - start:.2f} - Video length {video_length:.2f} - relative speed {video_length/(end - start):.1f}x"
    )

    subs = pysrt.SubRipFile()
    sub_idx = 1
    item_count = len(result["segments"])
    lines = []

    for i in range(item_count):
        start_time = result["segments"][i]["start"]
        end_time = result["segments"][i]["end"]
        duration = end_time - start_time
        timestamp = f"{start_time:.3f} - {end_time:.3f}"
        text = result["segments"][i]["text"]

        sub = pysrt.SubRipItem(
            index=sub_idx,
            start=pysrt.SubRipTime(seconds=start_time),
            end=pysrt.SubRipTime(seconds=end_time),
            text=text,
        )
        lines.append(text)
        subs.append(sub)
        sub_idx += 1

    if not subs:
        print(f"Subtitle empty {sub_zho}")

    else:
        subs.save(sub_zho)

        with open(txt_sub, "w", encoding="utf-8") as file:
            file.write("\n".join(lines))

        print(f"Subtitle written {sub_zho}")
        print(f"Waiting for new video files in {MEDIA_DIR}...")

    shutil.move(media_file, new_media_file)


if __name__ == "__main__":
    main()
