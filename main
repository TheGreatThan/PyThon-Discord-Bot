import discord
from discord.ext import commands
import youtube_dl
import os

from discord.ext import commands, tasks

from random import choice

client = commands.Bot(command_prefix="?")


@client.command()
async def join(ctx):
    if not ctx.message.author.voice:
        await ctx.send("❗❓You are not connected to a voice channel!⚠")
        return

    else:
        channel = ctx.message.author.voice.channel

    await channel.connect()
    await ctx.send('☑Connected!☑')


@client.command()
async def leave(ctx):
    if not ctx.message.author.voice:
        await ctx.send("❗❓You are not connected to a voice channel!⚠")
        return

    else:
        voice_client = ctx.message.guild.voice_client
        await voice_client.disconnect()
        await ctx.send('☑Disconnected!☑')


@client.command()
async def play(ctx, url: str):
    song_there = os.path.isfile("song.mp3")
    try:
        if song_there:
            os.remove("song.mp3")
    except PermissionError:
        await ctx.send(
            "Wait for the current playing music to end or use the 'stop' command"
        )
        return

    voiceChannel = discord.utils.get(ctx.guild.voice_channels, name='General')
    await voiceChannel.connect()
    await ctx.send("💡connected!💡")
    voice = discord.utils.get(client.voice_clients, guild=ctx.guild)

    ydl_opts = {
        'format':
        'bestaudio/best',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
    }
    with youtube_dl.YoutubeDL(ydl_opts) as ydl:
        await ctx.send("⏳Please Wait While We Downloading Your Song...🔔")
        await ctx.send("⏳Its May Took 0 to 2 mins!⏳")
        ydl.download([url])
    for file in os.listdir("./"):
        if file.endswith(".mp3"):
            os.rename(file, "song.mp3")
    voice.play(discord.FFmpegPCMAudio("song.mp3"))
    await ctx.send("🎶Loading Succeeded! Now Playing🎶")


@client.command()
async def dis(ctx):
    voice = discord.utils.get(client.voice_clients, guild=ctx.guild)
    if voice.is_connected():
        if not ctx.message.author.voice:
            await ctx.send("❗❓You are not connected to a voice channel!⚠")
        else:
            await voice.disconnect()
            await ctx.send("⭕Disconnected!")
    else:
        await ctx.send("❌The bot is not connected to a voice channel.")


@client.command()
async def pause(ctx):
    voice = discord.utils.get(client.voice_clients, guild=ctx.guild)
    if voice.is_playing():
        voice.pause()
        await ctx.send("✔Paused!")
    else:
        await ctx.send("⚠Currently no audio is playing!")


@client.command()
async def die(ctx):
    responses = [
        'Why have you brought my short life to an end',
        'I could have done so much more', 'I have a family, kill them instead',
        'What have I done to you ?'
    ]
    await ctx.send(choice(responses))


@client.command()
async def hello(ctx):
    responses = [
        '***grumble*** Why did you wake me up?',
        'Top of the morning to you lad!', 'Hello, how are you?', 'Hi',
        '**Wasssuup! Its PewDiePie Here Guys!**'
    ]
    await ctx.send(choice(responses))


@client.command()
async def dytmemay(ctx):
    responses = [
        '***grumble*** WHAT DID U SAY TO ME U LITTLE SHIT',
        'DUMA CAN U SAY IT AGAIN DUMBASS?', 'Hello, DIT ME YOU TOO',
        '**Im dont reply to trash...**'
    ]
    await ctx.send(choice(responses))


@client.command()
async def ping(ctx):
    await ctx.send(f'**Pong!** Latency: {round(client.latency * 1000)}ms')


@client.command(name='credits', help='This command returns the credits')
async def cre(ctx):
    await ctx.send('Made by `Than#1272`')
    await ctx.send('Thank for using my bot!')


@client.command()
async def resume(ctx):
    voice = discord.utils.get(client.voice_clients, guild=ctx.guild)
    if voice.is_paused():
        voice.resume()
    else:
        await ctx.send("⚠The audio is not paused!")


@client.command()
async def stop(ctx):
    voice = discord.utils.get(client.voice_clients, guild=ctx.guild)
    voice.stop()
    await ctx.send("✔Stopped!")
\\ here i

status = [
    'Prefix`?`', 'Fact: Cookie with Milk is the best!', 'Creator: Than#1272',
    'Willy Wonka Was Here.'
]


@client.event
async def on_ready():
    change_status.start()
    print('Bot is online!')


@tasks.loop(seconds=20)
async def change_status():
    await client.change_presence(activity=discord.Game(choice(status)))


@client.command()
async def a(ctx):
    responses = [
        'stop, that not funny anymore...',
        ' why?`a` is not a reason to type or spam...', 'No comment.'
    ]
    await ctx.send(choice(responses))


client.run('YOUR BOT TOKEN HERE')
