import discord
from discord.ext import commands, tasks
import yt_dlp as youtube_dl
import os
from dotenv import load_dotenv
from random import choice
import asyncio

# --- SETUP ---
load_dotenv()
TOKEN = os.getenv('TOKEN')

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True

client = commands.Bot(command_prefix="?", intents=intents)

# A dictionary to hold the song queues for each server (guild)
queues = {}

status = [
    'Prefix `?`',
    'Fact: Cookie with Milk is the best!',
    'Creator: Than#1272',
    'Willy Wonka Was Here.'
]


# --- EVENTS & TASKS ---
@client.event
async def on_ready():
    change_status.start()
    print(f'Bot is online as {client.user}!')


@tasks.loop(seconds=20)
async def change_status():
    await client.change_presence(activity=discord.Game(choice(status)))


# --- QUEUE PLAYER & HELPER ---

def play_next(ctx):
    """A helper function that plays the next song in the queue."""
    if ctx.guild.id in queues and queues[ctx.guild.id]:
        song = queues[ctx.guild.id].pop(0)

        # Wrap the source in a volume transformer to make it controllable
        transformed_source = discord.PCMVolumeTransformer(song['source'])

        # The 'after' parameter calls this function again when the song finishes
        ctx.voice_client.play(transformed_source, after=lambda e: play_next(ctx))

        # Send a message to the channel in a thread-safe way
        asyncio.run_coroutine_threadsafe(ctx.send(f"🎶 Now Playing: **{song['title']}** 🎶"), client.loop)


# --- VOICE COMMANDS ---

@client.command(name='join', help='Tells the bot to join the voice channel')
async def join(ctx):
    if not ctx.message.author.voice:
        await ctx.send("❗ You are not connected to a voice channel! ⚠")
        return
    else:
        channel = ctx.message.author.voice.channel

    if ctx.voice_client is not None:
        return await ctx.voice_client.move_to(channel)

    await channel.connect()
    await ctx.send(f'☑ Connected to **{channel}**! ☑')


@client.command(name='leave', help='To make the bot leave the voice channel')
async def leave(ctx):
    # Clear the queue when the bot leaves
    if ctx.guild.id in queues:
        queues.pop(ctx.guild.id)

    voice_client = ctx.message.guild.voice_client
    if voice_client and voice_client.is_connected():
        await voice_client.disconnect()
        await ctx.send('☑ Disconnected! ☑')
    else:
        await ctx.send("❌ The bot is not connected to a voice channel.")


@client.command(name='play', help='To play a song or add it to the queue')
async def play(ctx, *, url: str):
    """Plays a song from a URL or adds it to the queue if a song is already playing."""
    if not ctx.author.voice:
        await ctx.send("You need to be in a voice channel to use this command!")
        return

    voice_client = ctx.voice_client
    if not voice_client:
        voice_client = await ctx.author.voice.channel.connect()

    await ctx.send("⏳ Searching for your song...")

    ydl_opts = {
        'format': 'bestaudio/best',
        'noplaylist': True,
        'quiet': True,
    }

    try:
        with youtube_dl.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            song_url = info['url']
            title = info['title']
            source = discord.FFmpegPCMAudio(song_url,
                                            before_options="-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
                                            options="-vn")
            song = {'source': source, 'title': title}
    except Exception as e:
        await ctx.send(f"An error occurred: {e}")
        return

    if ctx.guild.id not in queues:
        queues[ctx.guild.id] = []

    queues[ctx.guild.id].append(song)
    await ctx.send(f"✅ Added **{title}** to the queue!")

    if not voice_client.is_playing():
        play_next(ctx)


@client.command(name='volume', help='Changes the bot\'s volume (0-200)')
async def volume(ctx, vol: int):
    """Changes the player's volume."""
    voice_client = ctx.voice_client
    if not voice_client or not voice_client.is_playing():
        return await ctx.send("I'm not currently playing anything.")

    if not 0 <= vol <= 200:
        return await ctx.send("Please enter a volume between 0 and 200.")

    # Check if the source is a PCMVolumeTransformer
    if isinstance(voice_client.source, discord.PCMVolumeTransformer):
        voice_client.source.volume = vol / 100
        await ctx.send(f"🔊 Set volume to **{vol}%**")
    else:
        await ctx.send("Volume cannot be changed on this audio source.")


@client.command(name='queue', help='Displays the current song queue')
async def queue(ctx):
    if ctx.guild.id not in queues or not queues[ctx.guild.id]:
        await ctx.send("The queue is currently empty!")
        return

    queue_list = ""
    for i, song in enumerate(queues[ctx.guild.id]):
        queue_list += f"{i + 1}. {song['title']}\n"

    await ctx.send(f"**Up Next:**\n{queue_list}")


@client.command(name='skip', help='Skips the current song')
async def skip(ctx):
    voice_client = ctx.voice_client
    if voice_client and voice_client.is_playing():
        voice_client.stop()
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
    voice_client = ctx.message.guild.voice_client
    if voice_client and voice_client.is_playing():
        voice_client.pause()
        await ctx.send("✔ Paused! ✔")
    else:
        await ctx.send("⚠ Currently no audio is playing!")


@client.command(name='resume', help='Resumes the song')
async def resume(ctx):
    voice_client = ctx.message.guild.voice_client
    if voice_client and voice_client.is_paused():
        voice_client.resume()
        await ctx.send("▶ Resumed! ▶")
    else:
        await ctx.send("⚠ The audio is not paused!")


@client.command(name='stop', help='Stops the music and clears the queue')
async def stop(ctx):
    if ctx.guild.id in queues:
        queues[ctx.guild.id].clear()

    voice_client = ctx.message.guild.voice_client
    if voice_client and voice_client.is_playing():
        voice_client.stop()
        await ctx.send("⏹️ Stopped the music and cleared the queue.")
    else:
        await ctx.send("⚠ Nothing is playing to stop!")


# --- MISC & FUN COMMANDS ---
@client.command()
async def ping(ctx):
    await ctx.send(f'**Pong!** Latency: {round(client.latency * 1000)}ms')


@client.command(name='credits')
async def credits(ctx):
    await ctx.send('Made by `Than#1272`')
    await ctx.send('Thank you for using my bot!')
    await ctx.send('Special thanks to Gemini Pro for debugging the old code!')


@client.command()
async def die(ctx):
    responses = ['Why have you brought my short life to an end?', 'I could have done so much more.',
                 'I have a family, kill them instead.']
    await ctx.send(choice(responses))


@client.command()
async def hello(ctx):
    responses = ['***grumble*** Why did you wake me up?', 'Top of the morning to you lad!', 'Hello, how are you?',
                 'Hi!']
    await ctx.send(choice(responses))


# --- RUN THE BOT ---
client.run(TOKEN)
