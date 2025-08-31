import discord
from discord.ext import commands, tasks
import yt_dlp as youtube_dl
import os
from dotenv import load_dotenv
from random import choice
import asyncio
import re
import time

# --- SETUP ---
load_dotenv()
TOKEN = os.getenv('TOKEN')

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True

client = commands.Bot(command_prefix="?", intents=intents)

# Dictionaries to hold queues and currently playing song info
queues = {}
now_playing = {}

status = ['Prefix `?`', 'Creator: Than#1272']


# --- HELPER FUNCTIONS ---

def format_duration(seconds):
    """Formats seconds into a MM:SS or HH:MM:SS string."""
    if seconds is None: return 'N/A'
    minutes, seconds = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    return f'{hours:02d}:{minutes:02d}:{seconds:02d}' if hours > 0 else f'{minutes:02d}:{seconds:02d}'


def parse_duration(timestamp):
    """Parses a MM:SS or HH:MM:SS string into seconds."""
    parts = list(map(int, timestamp.split(':')))
    if len(parts) == 2: return parts[0] * 60 + parts[1]
    if len(parts) == 3: return parts[0] * 3600 + parts[1] * 60 + parts[2]
    return 0


def after_playback(ctx, filepath):
    """Callback function to clean up the audio file and play the next song."""
    if os.path.exists(filepath):
        try:
            os.remove(filepath)
        except Exception as e:
            print(f"Error deleting file {filepath}: {e}")
    play_next(ctx)


def start_playing(ctx, song, seek_offset=0):
    """Helper function to start playing a song, with an optional seek time."""
    now_playing[ctx.guild.id] = song
    song['start_time'] = time.time() - seek_offset

    ffmpeg_options = {'options': '-vn'}
    if seek_offset > 0:
        ffmpeg_options['options'] += f' -ss {seek_offset}'

    source = discord.FFmpegPCMAudio(song['filepath'], **ffmpeg_options)
    transformed_source = discord.PCMVolumeTransformer(source)

    ctx.voice_client.play(transformed_source, after=lambda e: after_playback(ctx, song['filepath']))

    message = f"🎶 Now Playing: **{song['title']}**"
    if seek_offset > 0: message += f" (started at {format_duration(seek_offset)})"

    asyncio.run_coroutine_threadsafe(ctx.send(message), client.loop)


def play_next(ctx):
    """Plays the next song in the queue."""
    if ctx.guild.id in queues and queues[ctx.guild.id]:
        song = queues[ctx.guild.id].pop(0)
        start_playing(ctx, song)
    else:
        if ctx.guild.id in now_playing:
            now_playing.pop(ctx.guild.id)


# --- EVENTS & TASKS ---
@client.event
async def on_ready():
    change_status.start()
    print(f'Bot is online as {client.user}!')


@tasks.loop(seconds=20)
async def change_status():
    await client.change_presence(activity=discord.Game(choice(status)))


# --- VOICE COMMANDS ---

@client.command(name='join', help='Tells the bot to join the voice channel')
async def join(ctx):
    if not ctx.message.author.voice:
        return await ctx.send("❗ You are not connected to a voice channel! ⚠")
    channel = ctx.message.author.voice.channel
    if ctx.voice_client is not None:
        return await ctx.voice_client.move_to(channel)
    await channel.connect()


@client.command(name='leave', help='To make the bot leave the voice channel')
async def leave(ctx):
    if ctx.guild.id in queues: queues.pop(ctx.guild.id)
    if ctx.guild.id in now_playing: now_playing.pop(ctx.guild.id)
    if ctx.voice_client and ctx.voice_client.is_connected():
        await ctx.voice_client.disconnect()


@client.command(name='play', help='Searches for and plays a song by name or URL')
async def play(ctx, *, query: str):
    if not ctx.author.voice:
        return await ctx.send("You need to be in a voice channel to use this command!")
    if not ctx.voice_client:
        await ctx.author.voice.channel.connect()

    await ctx.send("⏳ Searching and downloading...")

    script_dir = os.path.dirname(os.path.abspath(__file__))
    is_url = query.strip().startswith('http')
    search_query = query

    if not is_url:
        delimiters = r'\s+(by|artist|musician)[:\s]\s+'
        parts = re.split(delimiters, query, maxsplit=1, flags=re.IGNORECASE)
        if len(parts) == 3: search_query = f"{parts[0]} {parts[2]}"
        search_query = f"ytsearch:{search_query}"

    try:
        with youtube_dl.YoutubeDL({'quiet': True, 'noplaylist': True}) as ydl:
            info = ydl.extract_info(search_query, download=False)
            if '_type' in info and info['_type'] == 'playlist': info = info['entries'][0]
            video_id, title, duration = info.get('id', 'unknown'), info.get('title', 'Unknown'), info.get('duration', 0)

        base_filepath = os.path.join(script_dir, video_id)
        ydl_opts = {'format': 'bestaudio/best', 'outtmpl': base_filepath, 'quiet': True, 'noplaylist': True}
        with youtube_dl.YoutubeDL(ydl_opts) as ydl:
            ydl.download([info['webpage_url']])

        downloaded_file = None
        for file in os.listdir(script_dir):
            if file.startswith(video_id):
                downloaded_file = os.path.join(script_dir, file)
                break
        if not downloaded_file: return await ctx.send("❌ Error: Could not find the downloaded file.")

        song = {'filepath': downloaded_file, 'title': title, 'duration': duration}

    except Exception as e:
        return await ctx.send(f"An error occurred during download.\n`{e}`")

    if ctx.guild.id not in queues: queues[ctx.guild.id] = []
    queues[ctx.guild.id].append(song)
    await ctx.send(f"✅ Added **{title}** to the queue!")

    if not ctx.voice_client.is_playing():
        play_next(ctx)


@client.command(name='np', help='Shows the currently playing song with a live progress bar')
async def np(ctx):
    """Displays a live-updating embed for the currently playing song."""
    if ctx.guild.id not in now_playing:
        return await ctx.send("Nothing is currently playing.")

    song = now_playing[ctx.guild.id]

    # --- Create the initial embed ---
    title = song['title']
    duration = song['duration']
    elapsed_time = time.time() - song['start_time']

    # --- Custom Progress Bar Logic ("Slider Knob") ---
    progress_bar_length = 20
    empty_char = '▬'
    knob = '🔘'
    progress = int((elapsed_time / duration) * (progress_bar_length - 1))
    progress = max(0, min(progress, progress_bar_length - 1))
    progress_bar = empty_char * progress + knob + empty_char * (progress_bar_length - 1 - progress)

    elapsed_str = format_duration(elapsed_time)
    duration_str = format_duration(duration)

    embed = discord.Embed(title="Now Playing", description=f"**{title}**", color=discord.Color.blue())
    embed.add_field(name="Progress", value=f"`{elapsed_str} / {duration_str}`\n`[{progress_bar}]`", inline=False)

    message = await ctx.send(embed=embed)

    # --- Loop to update the message ---
    while ctx.voice_client and ctx.voice_client.is_playing():
        await asyncio.sleep(5)

        elapsed_time = time.time() - song['start_time']
        if elapsed_time > duration: break

        # --- Update Progress Bar ---
        progress = int((elapsed_time / duration) * (progress_bar_length - 1))
        progress = max(0, min(progress, progress_bar_length - 1))
        progress_bar = empty_char * progress + knob + empty_char * (progress_bar_length - 1 - progress)
        elapsed_str = format_duration(elapsed_time)

        new_embed = discord.Embed(title="Now Playing", description=f"**{title}**", color=discord.Color.blue())
        new_embed.add_field(name="Progress", value=f"`{elapsed_str} / {duration_str}`\n`[{progress_bar}]`",
                            inline=False)

        try:
            await message.edit(embed=new_embed)
        except discord.NotFound:
            break


@client.command(name='seek', help='Skips to a specific timestamp in the song (e.g., 1:23)')
async def seek(ctx, *, timestamp: str):
    if ctx.guild.id not in now_playing:
        return await ctx.send("Nothing is currently playing.")
    if not ctx.voice_client or not ctx.voice_client.is_playing():
        return await ctx.send("I'm not connected or playing anything.")
    song = now_playing[ctx.guild.id]
    try:
        seek_in_seconds = parse_duration(timestamp)
        if not 0 <= seek_in_seconds < song['duration']:
            return await ctx.send("Invalid timestamp. It's outside the song's duration.")
    except:
        return await ctx.send("Invalid timestamp format. Please use `MM:SS` or `HH:MM:SS`.")
    ctx.voice_client.stop()
    await asyncio.sleep(0.5)
    start_playing(ctx, song, seek_offset=seek_in_seconds)


@client.command(name='volume', help='Changes the bot\'s volume (0-200)')
async def volume(ctx, vol: int):
    if not ctx.voice_client or not ctx.voice_client.is_playing():
        return await ctx.send("I'm not currently playing anything.")
    if not 0 <= vol <= 200:
        return await ctx.send("Please enter a volume between 0 and 200.")
    if isinstance(ctx.voice_client.source, discord.PCMVolumeTransformer):
        ctx.voice_client.source.volume = vol / 100
        await ctx.send(f"🔊 Set volume to **{vol}%**")


@client.command(name='queue', help='Displays the current song queue')
async def queue(ctx):
    if not (ctx.guild.id in queues and queues[ctx.guild.id]) and not (ctx.guild.id in now_playing):
        return await ctx.send("The queue is currently empty!")
    now_playing_info = f"**Now Playing:** {now_playing[ctx.guild.id]['title']}\n\n" if ctx.guild.id in now_playing else ""
    queue_list = "".join([f"{i + 1}. {song['title']}\n" for i, song in enumerate(queues[ctx.guild.id])])
    await ctx.send(f"{now_playing_info}**Up Next:**\n{queue_list if queue_list else 'Nothing'}")


@client.command(name='skip', help='Skips the current song')
async def skip(ctx):
    if ctx.voice_client and ctx.voice_client.is_playing():
        ctx.voice_client.stop()
        await ctx.send("⏭️ Skipped!")
    else:
        await ctx.send("There is no song to skip.")


@client.command(name='clear', help='Clears the entire song queue')
async def clear(ctx):
    if ctx.guild.id in queues and queues[ctx.guild.id]:
        queues[ctx.guild.id].clear()
        await ctx.send("✅ Queue has been cleared!")
    else:
        await ctx.send("The queue is already empty.")


@client.command(name='pause', help='This command pauses the song')
async def pause(ctx):
    if ctx.voice_client and ctx.voice_client.is_playing():
        ctx.voice_client.pause()
        await ctx.send("✔ Paused! ✔")


@client.command(name='resume', help='Resumes the song')
async def resume(ctx):
    if ctx.voice_client and ctx.voice_client.is_paused():
        ctx.voice_client.resume()
        await ctx.send("▶ Resumed! ▶")


@client.command(name='stop', help='Stops the music and clears the queue')
async def stop(ctx):
    if ctx.guild.id in queues:
        # Clean up files for songs that were in the queue
        for song in queues[ctx.guild.id]:
            if os.path.exists(song['filepath']):
                os.remove(song['filepath'])
        queues[ctx.guild.id].clear()
    if ctx.voice_client and ctx.voice_client.is_playing():
        ctx.voice_client.stop()
        await ctx.send("⏹️ Stopped the music and cleared the queue.")


# --- MISC & FUN COMMANDS ---
@client.command()
async def ping(ctx):
    await ctx.send(f'**Pong!** Latency: {round(client.latency * 1000)}ms')


# --- RUN THE BOT ---
client.run(TOKEN)
