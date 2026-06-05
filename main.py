import discord
from discord.ext import commands, tasks
from discord import app_commands
import yt_dlp as youtube_dl
import os
from dotenv import load_dotenv
from random import choice
import random
import asyncio
import time
import aiohttp
import json

# --- SETUP ---
load_dotenv()
TOKEN = ''  # <--- DÁN TOKEN CỦA BẠN VÀO ĐÂY

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True

client = commands.Bot(command_prefix="?", intents=intents, help_command=None)

# DATA STORAGE
queues = {}
now_playing = {}
volumes = {}
loop_states = {}
audio_filters = {}

status = ['Prefix `?`', 'Nghe nhạc cực chill 🎧', 'Gõ /pf để mở Tủ Nhạc! ❤️']

# --- HỆ THỐNG LƯU TRỮ TỦ NHẠC (FAVORITES) ---
FAV_FILE = "favorites.json"


def load_favs():
    if not os.path.exists(FAV_FILE):
        return {}
    with open(FAV_FILE, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {}


def save_favs(data):
    with open(FAV_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)


# Context giả lập cho lệnh Slash
class MockCtx:
    def __init__(self, interaction):
        self.guild = interaction.guild
        self.author = interaction.user
        self.voice_client = interaction.guild.voice_client
        self.channel = interaction.channel

    async def send(self, *args, **kwargs):
        return await self.channel.send(*args, **kwargs)


# --- CẤU HÌNH YT-DLP ---
yt_dlp_opts = {
    'format': 'bestaudio/best',
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0',
    'http_headers': {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    },
}

ffmpeg_options = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn -ar 48000 -ac 2 -b:a 192k'
}

COLOR_MAIN = 0x2b2d31
COLOR_SUCCESS = 0x57F287
COLOR_WARN = 0xFEE75C
COLOR_ERROR = 0xED4245


def create_embed(title, description, color=COLOR_MAIN):
    return discord.Embed(title=title, description=description, color=color)


def format_duration(seconds):
    if seconds is None or seconds == 0: return 'Live'
    minutes, seconds = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    return f'{hours:02d}:{minutes:02d}:{seconds:02d}' if hours > 0 else f'{minutes:02d}:{seconds:02d}'


def create_progress_bar(current, total, length=20):
    if total == 0: return "🔘" + "▬" * length
    percent = current / total
    if percent > 1: percent = 1
    filled_length = int(length * percent)
    bar = "▬" * filled_length + "🔘" + "▬" * (length - filled_length)
    return f"`{bar}`"


# --- BẢNG ĐIỀU KHIỂN NÚT BẤM (UI VIEW) ---
class SpeedSelect(discord.ui.Select):
    def __init__(self, ctx):
        options = [
            discord.SelectOption(label="Tốc độ: 0.5x (Chậm)", value="0.5", emoji="🐢"),
            discord.SelectOption(label="Tốc độ: 1.0x (Chuẩn)", value="1.0", emoji="▶️"),
            discord.SelectOption(label="Tốc độ: 1.25x (Hơi nhanh)", value="1.25", emoji="🐇"),
            discord.SelectOption(label="Tốc độ: 1.5x (Nhanh)", value="1.5", emoji="🔥"),
            discord.SelectOption(label="Tốc độ: 2.0x (Siêu tốc)", value="2.0", emoji="🚀"),
        ]
        super().__init__(placeholder="⚡ Chọn Tốc Độ Phát...", min_values=1, max_values=1, options=options, row=2)
        self.ctx = ctx

    async def callback(self, interaction: discord.Interaction):
        if not self.ctx.voice_client: return await interaction.response.send_message("❌ Bot đã ngắt kết nối!",
                                                                                     ephemeral=True)
        if not interaction.user.voice or interaction.user.voice.channel != self.ctx.voice_client.channel:
            return await interaction.response.send_message("❌ Bạn không ở trong kênh thoại cùng bot!", ephemeral=True)

        speed = float(self.values[0])
        guild_id = self.ctx.guild.id
        if guild_id in now_playing:
            now_playing[guild_id]['speed'] = speed
            elapsed = time.time() - now_playing[guild_id]['start_time']
            now_playing[guild_id]['seeking'] = True
            now_playing[guild_id]['target_seek'] = elapsed
            now_playing[guild_id]['announce_seek'] = True
            self.ctx.voice_client.stop()
            await interaction.response.send_message(f"🚀 Đã chỉnh tốc độ sang **{speed}x**.", ephemeral=True)


class SkipToSelect(discord.ui.Select):
    def __init__(self, ctx, start_idx=0, end_idx=25, row=3, placeholder=""):
        self.ctx = ctx
        self.start_idx = start_idx
        self.end_idx = end_idx
        options = self.get_options()
        super().__init__(placeholder=placeholder, min_values=1, max_values=1, options=options, row=row)
        self.disabled = (options[0].value == "0")

    def get_options(self):
        guild_id = self.ctx.guild.id
        q = queues.get(guild_id, [])
        opts = []
        slice_q = q[self.start_idx:self.end_idx]
        if not slice_q:
            opts.append(
                discord.SelectOption(label="Hàng đợi đang trống", value="0", description="Không có bài hát ở đoạn này",
                                     emoji="🈳"))
        else:
            for i, song in enumerate(slice_q):
                actual_idx = self.start_idx + i + 1
                title = song['title']
                if len(title) > 90: title = title[:90] + "..."
                opts.append(discord.SelectOption(label=f"{actual_idx}. {title}", value=str(actual_idx), emoji="🎵"))
        return opts

    async def callback(self, interaction: discord.Interaction):
        if not self.ctx.voice_client: return await interaction.response.send_message("❌ Bot đã ngắt kết nối!",
                                                                                     ephemeral=True)
        if not interaction.user.voice or interaction.user.voice.channel != self.ctx.voice_client.channel:
            return await interaction.response.send_message("❌ Bạn không ở trong kênh thoại cùng bot!", ephemeral=True)
        if self.values[0] == "0": return await interaction.response.send_message("❌ Lựa chọn không hợp lệ!",
                                                                                 ephemeral=True)

        idx = int(self.values[0])
        guild_id = self.ctx.guild.id

        if guild_id not in queues or len(queues[guild_id]) < idx:
            return await interaction.response.send_message("❌ Lỗi: Bài hát không còn trong hàng đợi.", ephemeral=True)

        song_to_play = queues[guild_id].pop(idx - 1)
        queues[guild_id].insert(0, song_to_play)
        if self.ctx.voice_client and self.ctx.voice_client.is_playing(): self.ctx.voice_client.stop()
        await interaction.response.send_message(f"⏭️ Đã ưu tiên phát ngay bài **{song_to_play['title']}**!",
                                                ephemeral=True)


class MusicPlayerView(discord.ui.View):
    def __init__(self, ctx):
        super().__init__(timeout=None)
        self.ctx = ctx
        self.add_item(SpeedSelect(ctx))
        self.add_item(SkipToSelect(ctx, start_idx=0, end_idx=25, row=3, placeholder="⏭️ Chọn bài 1-25 (Nhảy cóc)"))
        if len(queues.get(ctx.guild.id, [])) > 25:
            self.add_item(
                SkipToSelect(ctx, start_idx=25, end_idx=50, row=4, placeholder="⏭️ Chọn bài 26-50 (Nhảy cóc)"))

    async def check_user(self, interaction: discord.Interaction):
        if not self.ctx.voice_client: return False
        if not interaction.user.voice or interaction.user.voice.channel != self.ctx.voice_client.channel:
            await interaction.response.send_message("❌ Bạn phải ở trong cùng kênh thoại với bot!", ephemeral=True)
            return False
        return True

    @discord.ui.button(emoji="⏯️", style=discord.ButtonStyle.primary, custom_id="btn_playpause", row=0)
    async def toggle_play(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.check_user(interaction): return
        vc = self.ctx.voice_client
        if vc.is_playing():
            vc.pause()
            await interaction.response.send_message("⏸️ Đã tạm dừng nhạc.", ephemeral=True)
        elif vc.is_paused():
            vc.resume()
            await interaction.response.send_message("▶️ Tiếp tục phát nhạc.", ephemeral=True)

    @discord.ui.button(emoji="⏭️", style=discord.ButtonStyle.secondary, custom_id="btn_skip", row=0)
    async def skip_song(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.check_user(interaction): return
        vc = self.ctx.voice_client
        if vc and vc.is_playing():
            if loop_states.get(self.ctx.guild.id, {}).get('mode') == 'song':
                loop_states[self.ctx.guild.id] = {'mode': 'none', 'count': 0}
            vc.stop()
            await interaction.response.send_message("⏭️ Đã next qua bài mới!", ephemeral=True)

    @discord.ui.button(emoji="🔁", style=discord.ButtonStyle.success, custom_id="btn_loop", row=0)
    async def loop_song(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.check_user(interaction): return
        guild_id = self.ctx.guild.id
        current_loop = loop_states.get(guild_id, {}).get('mode')
        if current_loop == 'song':
            loop_states[guild_id] = {'mode': 'queue', 'count': -1}
            await interaction.response.send_message("🔁 Đã bật lặp **Hàng Đợi**.", ephemeral=True)
        elif current_loop == 'queue':
            loop_states[guild_id] = {'mode': 'none', 'count': 0}
            await interaction.response.send_message("➡️ Đã **TẮT** chế độ lặp.", ephemeral=True)
        else:
            loop_states[guild_id] = {'mode': 'song', 'count': -1}
            await interaction.response.send_message("🔂 Đã bật lặp **Bài Hiện Tại**.", ephemeral=True)

    @discord.ui.button(emoji="⏹️", style=discord.ButtonStyle.danger, custom_id="btn_stop", row=0)
    async def stop_song(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.check_user(interaction): return
        queues[self.ctx.guild.id] = []
        loop_states[self.ctx.guild.id] = {'mode': 'none', 'count': 0}
        if self.ctx.voice_client: self.ctx.voice_client.stop()
        await interaction.response.send_message("⏹️ Đã tắt nhạc.", ephemeral=True)

    @discord.ui.button(label="-15s", emoji="⏪", style=discord.ButtonStyle.secondary, custom_id="btn_rewind", row=1)
    async def rewind(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.check_user(interaction): return
        await self.seek_time(interaction, -15)

    @discord.ui.button(label="+15s", emoji="⏩", style=discord.ButtonStyle.secondary, custom_id="btn_fastforward", row=1)
    async def fastforward(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.check_user(interaction): return
        await self.seek_time(interaction, 15)

    @discord.ui.button(label="Lưu", emoji="❤️", style=discord.ButtonStyle.danger, custom_id="btn_fav", row=1)
    async def fav_song(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild_id = self.ctx.guild.id
        if guild_id not in now_playing:
            return await interaction.response.send_message("❌ Không có bài hát nào đang phát.", ephemeral=True)

        song = now_playing[guild_id]
        user_id = str(interaction.user.id)

        favs = load_favs()
        if user_id not in favs:
            favs[user_id] = []

        if any(s['url'] == song['webpage_url'] for s in favs[user_id]):
            return await interaction.response.send_message("⚠️ Bài này đã nằm trong tủ nhạc yêu thích của bạn rồi!",
                                                           ephemeral=True)

        favs[user_id].append({'title': song['title'], 'url': song['webpage_url']})
        save_favs(favs)

        await interaction.response.send_message(
            f"❤️ Đã cất **{song['title']}** vào Tủ Nhạc cá nhân của bạn! (Gõ `/pf` để mở)", ephemeral=True)

    async def seek_time(self, interaction, offset):
        guild_id = self.ctx.guild.id
        if guild_id not in now_playing: return
        song = now_playing[guild_id]
        elapsed = (time.time() - song['start_time']) * song.get('speed', 1.0)
        target = elapsed + offset
        if target < 0: target = 0
        if target >= song['duration']:
            self.ctx.voice_client.stop()
            return await interaction.response.send_message("⏭️ Đã chuyển bài tiếp theo.", ephemeral=True)
        song['seeking'] = True
        song['target_seek'] = target
        song['announce_seek'] = True
        self.ctx.voice_client.stop()
        await interaction.response.send_message(f"⏱️ Đã tua tới **{format_duration(target)}**", ephemeral=True)


# --- DASHBOARD TỦ NHẠC (/PF VIEW) ---
class FavPlaySelect(discord.ui.Select):
    def __init__(self, user_favs):
        # Dùng Index làm Value để tránh lỗi vượt 100 ký tự của URL
        self.sub_favs = list(reversed(user_favs[-25:]))
        options = [discord.SelectOption(label=s['title'][:100], value=str(i), emoji="▶️") for i, s in
                   enumerate(self.sub_favs)]
        super().__init__(placeholder="▶️ Chọn bài để PHÁT NGAY...", min_values=1, max_values=1, options=options,
                         custom_id="fav_play", row=0)

    async def callback(self, inter: discord.Interaction):
        if not inter.user.voice:
            return await inter.response.send_message("❌ Bạn chưa vào Voice Channel!", ephemeral=True)

        idx = int(self.values[0])
        song_data = self.sub_favs[idx]
        url = song_data['url']
        title = song_data['title']

        await inter.response.defer(ephemeral=True)
        if not inter.guild.voice_client:
            await inter.user.voice.channel.connect()

        if inter.guild.id not in queues: queues[inter.guild.id] = []
        queues[inter.guild.id].append({'webpage_url': url, 'title': title, 'speed': 1.0, 'requester': inter.user})

        await inter.followup.send(f"✅ Đã thêm **{title}** vào hàng đợi!", ephemeral=True)
        if not inter.guild.voice_client.is_playing(): await start_playing(MockCtx(inter))


class FavDeleteSelect(discord.ui.Select):
    def __init__(self, user_favs):
        self.sub_favs = list(reversed(user_favs[-25:]))
        options = [discord.SelectOption(label=s['title'][:100], value=str(i), emoji="🗑️") for i, s in
                   enumerate(self.sub_favs)]
        super().__init__(placeholder="🗑️ Chọn bài để XÓA khỏi tủ...", min_values=1, max_values=1, options=options,
                         custom_id="fav_del", row=1)

    async def callback(self, inter: discord.Interaction):
        idx = int(self.values[0])
        url_to_delete = self.sub_favs[idx]['url']

        user_id = str(inter.user.id)
        favs = load_favs()

        favs[user_id] = [s for s in favs.get(user_id, []) if s['url'] != url_to_delete]
        save_favs(favs)

        await inter.response.send_message("🗑️ Đã xoá bài hát khỏi Tủ Nhạc của bạn!", ephemeral=True)


class FavView(discord.ui.View):
    def __init__(self, user_favs):
        super().__init__(timeout=None)
        self.user_favs = user_favs
        self.add_item(FavPlaySelect(user_favs))
        self.add_item(FavDeleteSelect(user_favs))

    @discord.ui.button(label="Phát Toàn Bộ Tủ Nhạc", emoji="🎶", style=discord.ButtonStyle.success, row=2)
    async def play_all(self, inter: discord.Interaction, button: discord.ui.Button):
        if not inter.user.voice: return await inter.response.send_message("❌ Chui vào Voice Channel đi bạn ơi!",
                                                                          ephemeral=True)

        await inter.response.defer(ephemeral=True)
        if not inter.guild.voice_client: await inter.user.voice.channel.connect()
        if inter.guild.id not in queues: queues[inter.guild.id] = []

        for s in self.user_favs:
            queues[inter.guild.id].append({
                'webpage_url': s['url'], 'title': s['title'], 'speed': 1.0, 'requester': inter.user
            })

        await inter.followup.send(f"✅ Đã quăng toàn bộ **{len(self.user_favs)}** bài hát yêu thích vào hàng đợi!",
                                  ephemeral=True)
        if not inter.guild.voice_client.is_playing(): await start_playing(MockCtx(inter))


# ----------------------------------------
def play_next(ctx):
    asyncio.run_coroutine_threadsafe(start_playing(ctx), client.loop)


async def start_playing(ctx):
    guild_id = ctx.guild.id
    seek_offset = 0

    loop_state = loop_states.get(guild_id, {'mode': 'none', 'count': 0})
    last_song = now_playing.get(guild_id)

    if last_song and last_song.get('seeking', False):
        song = last_song
        seek_offset = song.get('target_seek', 0)
        song['seeking'] = False
    else:
        song = None
        if last_song and loop_state['mode'] == 'song':
            song = last_song.copy()
            song.pop('stream_url', None)
        if not song and last_song and loop_state['mode'] == 'queue':
            queues[guild_id].append(last_song.copy())
        if not song:
            if not queues.get(guild_id):
                now_playing.pop(guild_id, None)
                loop_states[guild_id] = {'mode': 'none', 'count': 0}
                return await ctx.send(
                    embed=create_embed("✨ Buổi tiệc kết thúc!", "Hàng đợi đã trống. Ném link vào đây để quẩy tiếp nào!",
                                       COLOR_SUCCESS))
            song = queues[guild_id].pop(0)

    try:
        if 'stream_url' not in song or seek_offset > 0:
            loop = client.loop
            with youtube_dl.YoutubeDL(yt_dlp_opts) as ydl:
                info = await loop.run_in_executor(None, lambda: ydl.extract_info(song['webpage_url'], download=False))
                if 'url' in info:
                    song['stream_url'] = info['url']
                else:
                    formats = info.get('formats', [info])
                    best_audio = next((f for f in formats if f.get('acodec') != 'none' and f.get('vcodec') == 'none'),
                                      formats[0])
                    song['stream_url'] = best_audio['url']

                song['duration'] = info.get('duration', song.get('duration', 0))
                song['thumbnail'] = info.get('thumbnail', song.get('thumbnail'))
                song['uploader'] = info.get('uploader', song.get('uploader', 'Unknown'))

    except Exception as e:
        return play_next(ctx)

    now_playing[guild_id] = song
    song['start_time'] = time.time() - seek_offset
    speed = song.get('speed', 1.0)
    current_filter = audio_filters.get(guild_id, 'clear')

    ff_opts = ffmpeg_options['options']
    audio_fx = []
    if speed != 1.0: audio_fx.append(f'atempo={speed}')
    if current_filter == 'bassboost':
        audio_fx.append('bass=g=15')
    elif current_filter == 'nightcore':
        audio_fx.append('asetrate=48000*1.25,atempo=1.25')
    elif current_filter == 'vaporwave':
        audio_fx.append('asetrate=48000*0.8,atempo=0.8')

    if audio_fx: ff_opts += f' -af "{" , ".join(audio_fx)}"'
    if seek_offset > 0: ff_opts += f' -ss {seek_offset}'

    try:
        if not ctx.voice_client: return
        source = discord.FFmpegPCMAudio(song['stream_url'], before_options=ffmpeg_options['before_options'],
                                        options=ff_opts)
        ctx.voice_client.play(discord.PCMVolumeTransformer(source, volume=volumes.get(guild_id, 1.0)),
                              after=lambda e: play_next(ctx))

        duration_str = format_duration(song['duration'])
        embed = discord.Embed(title="🎧 Đang Phát Nhạc", color=COLOR_MAIN)
        embed.description = f"### [{song['title']}]({song['webpage_url']})\n"
        if song.get('thumbnail'): embed.set_image(url=song['thumbnail'])

        embed.add_field(name="Kênh / Nguồn", value=f"`{song.get('uploader', 'Unknown')}`", inline=True)
        embed.add_field(name="Thời lượng", value=f"`{duration_str}`", inline=True)
        if speed != 1.0: embed.add_field(name="🚀 Tốc độ", value=f"`{speed}x`", inline=True)
        if current_filter != 'clear': embed.add_field(name="🎛️ Bộ lọc", value=f"`{current_filter.capitalize()}`",
                                                      inline=True)

        requester = song.get('requester')
        if requester: embed.set_footer(text=f"Nghe nhạc cực chill cùng {requester.display_name} 🌟",
                                       icon_url=requester.avatar.url if requester.avatar else None)

        if seek_offset == 0 or now_playing[guild_id].get('announce_seek', False):
            view = MusicPlayerView(ctx)
            sent_message = await ctx.send(embed=embed, view=view)
            now_playing[guild_id]['message_object'] = sent_message
            now_playing[guild_id]['view'] = view
            now_playing[guild_id]['announce_seek'] = False

    except Exception as e:
        play_next(ctx)


# --- EVENTS & TASKS ---
@client.event
async def on_ready():
    await client.tree.sync()
    change_status.start()
    periodic_update.start()
    print(f'Bot is online as {client.user}!')


@client.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound): return
    if isinstance(error, commands.CommandOnCooldown):
        await ctx.send(
            embed=create_embed("⏳ Chờ chút xíu", f"Bot đang cần thở, đợi `{error.retry_after:.2f}`s rồi thử lại nha!",
                               COLOR_WARN))


@tasks.loop(seconds=20)
async def change_status():
    await client.change_presence(activity=discord.Game(choice(status)))


@tasks.loop(seconds=5)
async def periodic_update():
    for guild_id, song in list(now_playing.items()):
        try:
            message = song.get('message_object')
            view = song.get('view')
            if not message or not view: continue

            guild = client.get_guild(guild_id)
            if not guild or not guild.voice_client or not guild.voice_client.is_playing(): continue

            elapsed = (time.time() - song['start_time']) * song.get('speed', 1.0)
            duration = song.get('duration', 0)

            curr_time_str = format_duration(elapsed)
            total_time_str = format_duration(duration)
            progress_bar = create_progress_bar(elapsed, duration)

            new_embed = discord.Embed(title="🎧 Đang Phát Nhạc", color=COLOR_MAIN)
            new_embed.description = f"### [{song['title']}]({song['webpage_url']})\n\n{progress_bar} `{curr_time_str} / {total_time_str}`"
            if song.get('thumbnail'): new_embed.set_image(url=song['thumbnail'])

            new_embed.add_field(name="Kênh / Nguồn", value=f"`{song.get('uploader', 'Unknown')}`", inline=True)
            if song.get('speed', 1.0) != 1.0: new_embed.add_field(name="🚀 Tốc độ", value=f"`{song['speed']}x`",
                                                                  inline=True)
            filter_name = audio_filters.get(guild_id, 'clear')
            if filter_name != 'clear': new_embed.add_field(name="🎛️ Bộ lọc", value=f"`{filter_name.capitalize()}`",
                                                           inline=True)

            requester = song.get('requester')
            if requester: new_embed.set_footer(text=f"Nghe nhạc cực chill cùng {requester.display_name} 🌟",
                                               icon_url=requester.avatar.url if requester.avatar else None)

            q_len = len(queues.get(guild_id, []))
            items_to_remove = [x for x in view.children if isinstance(x, SkipToSelect)]
            for item in items_to_remove: view.remove_item(item)

            view.add_item(
                SkipToSelect(view.ctx, start_idx=0, end_idx=25, row=3, placeholder="⏭️ Chọn bài 1-25 (Nhảy cóc)"))
            if q_len > 25: view.add_item(
                SkipToSelect(view.ctx, start_idx=25, end_idx=50, row=4, placeholder="⏭️ Chọn bài 26-50 (Nhảy cóc)"))

            await message.edit(embed=new_embed, view=view)
        except Exception:
            pass


# --- LỆNH SLASH ĐA NĂNG (/pf) ---
async def fav_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    user_id = str(interaction.user.id)
    favs = load_favs().get(user_id, [])
    rev_favs = list(reversed(favs))
    choices = []

    for i, fav in enumerate(rev_favs):
        if current.lower() in fav['title'].lower():
            # Dùng Index làm value thay vì URL để lách luật 100 kí tự của Discord
            choices.append(app_commands.Choice(name=fav['title'][:100], value=str(i)))
            if len(choices) == 25: break
    return choices


@client.tree.command(name="pf", description="🎵 Mở Tủ Nhạc Hoặc Phát Nhanh Bài Hát")
@app_commands.autocomplete(song=fav_autocomplete)
@app_commands.describe(song="🔍 Bỏ trống để mở menu, hoặc gõ tên bài để phát luôn!")
async def pf_command(interaction: discord.Interaction, song: str = None):
    # Đã bọc Try..Except để chống crash ngầm
    await interaction.response.defer(ephemeral=True)
    try:
        user_id = str(interaction.user.id)
        favs = load_favs()
        user_favs = favs.get(user_id, [])

        if not user_favs:
            return await interaction.followup.send(
                "❌ Tủ nhạc của bạn đang trống vắng! Hãy dùng nút ❤️ ở dưới bài hát đang phát để cất nhạc vào tủ nha.",
                ephemeral=True)

        if song:
            try:
                idx = int(song)
                rev_favs = list(reversed(user_favs))
                matched_fav = rev_favs[idx]
                url = matched_fav['url']
                title = matched_fav['title']
            except ValueError:
                url = song
                title = "Nhạc yêu thích"

            if not interaction.user.voice: return await interaction.followup.send("❌ Bạn chưa vào Voice Channel!",
                                                                                  ephemeral=True)

            if not interaction.guild.voice_client: await interaction.user.voice.channel.connect()
            if interaction.guild.id not in queues: queues[interaction.guild.id] = []

            queues[interaction.guild.id].append({
                'webpage_url': url, 'title': title, 'speed': 1.0, 'requester': interaction.user
            })
            await interaction.followup.send(f"✅ Đã thêm **{title}** từ Tủ nhạc vào hàng đợi!", ephemeral=True)
            if not interaction.guild.voice_client.is_playing(): await start_playing(MockCtx(interaction))
            return

        embed = discord.Embed(title=f"❤️ Tủ Nhạc Của {interaction.user.display_name}",
                              description=f"Bạn đang có **{len(user_favs)}** bài hát yêu thích. Dùng thanh chọn dưới đây để quản lý nha!",
                              color=COLOR_SUCCESS)
        if interaction.user.avatar: embed.set_thumbnail(url=interaction.user.avatar.url)

        view = FavView(user_favs)
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    except Exception as e:
        print(f"Lỗi lệnh /pf: {e}")
        await interaction.followup.send(f"❌ Có lỗi xảy ra khi mở tủ nhạc: {e}", ephemeral=True)


# --- TẤT CẢ COMMANDS CŨ ---
@client.command(name='help', aliases=['h'])
async def help_command(ctx):
    embed = discord.Embed(title="🤖 Danh Sách Lệnh Siêu Cấp",
                          description="Bạn có thể dùng bảng điều khiển ở dưới bài nhạc, hoặc gõ các lệnh thủ công nhé:",
                          color=COLOR_MAIN)
    if client.user.avatar: embed.set_thumbnail(url=client.user.avatar.url)

    command_list = [cmd for cmd in client.commands if cmd.name != 'help']
    for command in sorted(command_list, key=lambda cmd: cmd.name):
        if command.help:
            aliases = ', '.join([f"`?{a}`" for a in command.aliases])
            field_name = f"✨ `?{command.name}`"
            if aliases: field_name += f" *(Hoặc {aliases})*"
            embed.add_field(name=field_name, value=command.help, inline=False)

    embed.add_field(name="❤️ Lệnh Mới", value="Gõ `/pf` để mở tủ nhạc cá nhân của bạn.", inline=False)
    embed.set_footer(text="Gõ lệnh thả ga, nghe nhạc cực đã! 🎶",
                     icon_url=ctx.author.avatar.url if ctx.author.avatar else None)
    await ctx.send(embed=embed)


@client.command(name='sync', help='Ép Discord nạp lệnh Slash ngay lập tức')
async def sync_slash(ctx):
    msg = await ctx.send("⏳ Đang ép Discord nạp lệnh `/pf` vào server này, đợi xíu nha...")
    try:
        client.tree.copy_global_to(guild=ctx.guild)
        await client.tree.sync(guild=ctx.guild)
        await msg.edit(content="✅ Ép đồng bộ thành công! Bạn hãy gõ `/pf` thử xem nhé!")
    except Exception as e:
        await msg.edit(content=f"❌ Có lỗi xảy ra: {e}")


@client.command(name='join', help='Gọi bot vào phòng', aliases=['j'])
async def join(ctx):
    if not ctx.author.voice: return await ctx.send(
        embed=create_embed("❌ Ơ kìa!", "Bạn phải chui vào Voice Channel trước rồi mới gọi mình được chứ!", COLOR_ERROR))
    if ctx.voice_client:
        await ctx.voice_client.move_to(ctx.author.voice.channel)
    else:
        await ctx.author.voice.channel.connect()
    await ctx.send(
        embed=create_embed("🛬 Đã hạ cánh!", f"Đã có mặt tại **{ctx.author.voice.channel}**. Chuẩn bị quẩy thôi nào!",
                           COLOR_SUCCESS))


@client.command(name='leave', help='Đuổi bot khỏi phòng hiện tại', aliases=['dc', 'lv'])
async def leave(ctx):
    queues.pop(ctx.guild.id, None)
    now_playing.pop(ctx.guild.id, None)
    loop_states.pop(ctx.guild.id, None)
    audio_filters.pop(ctx.guild.id, None)
    if ctx.voice_client: await ctx.voice_client.disconnect()
    await ctx.send(
        embed=create_embed("👋 Tạm biệt nha", "Xong việc rồi, mình đi ngủ đây. Hẹn gặp lại nhé 💤", COLOR_MAIN))


@client.command(name='play', help='Phát nhạc lẻ hoặc Playlist (Spotify & YT)', aliases=['p'])
async def play(ctx, *, query: str):
    if not ctx.author.voice: return await ctx.send(
        embed=create_embed("❌ Lỗi", "Chưa vào phòng Voice mà đòi nghe nhạc à?", COLOR_ERROR))
    if not ctx.voice_client: await ctx.author.voice.channel.connect(timeout=20.0, reconnect=True)

    if not getattr(ctx, 'playnext', False):
        desc = f"Đang bới tung dữ liệu để tìm: **{query}**"
        wait_msg = await ctx.send(embed=discord.Embed(title="🔍 Đang xử lý...", description=desc, color=COLOR_WARN))

    if 'spotify.com' in query:
        if 'playlist' in query or 'album' in query:
            if 'wait_msg' in locals(): await wait_msg.delete()
            return await ctx.send(embed=create_embed("❌ Giới hạn bản quyền",
                                                     "Bot chỉ hỗ trợ phát **Bài hát lẻ** từ Spotify. Muốn nghe cả list, dùng link Playlist YouTube nhé!",
                                                     COLOR_ERROR))
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"https://open.spotify.com/oembed?url={query}") as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        query = f"{data.get('title', '')} {data.get('author_name', '')}"
                    else:
                        if 'wait_msg' in locals(): await wait_msg.delete()
                        return await ctx.send(
                            embed=create_embed("❌ Lỗi Spotify", "Link bị lỗi hoặc bài hát riêng tư.", COLOR_ERROR))
        except Exception:
            pass

    start_idx = 1
    end_idx = 50
    query_parts = query.split()
    if len(query_parts) > 1 and query_parts[-1].isdigit() and 'http' in query_parts[0]:
        target_end = int(query_parts[-1])
        if target_end > 0:
            end_idx = target_end
            start_idx = max(1, end_idx - 49)
        query = query_parts[0]

    is_search = not query.startswith('http')
    if is_search: query = f"ytsearch:{query}"

    if not is_search and ('list=' in query or 'playlist' in query):
        if 'wait_msg' in locals(): await wait_msg.edit(embed=discord.Embed(title="🔍 Đang nạp Playlist...",
                                                                           description=f"*Đang tải từ bài **{start_idx}** đến **{end_idx}** để tránh làm lag hệ thống...*",
                                                                           color=COLOR_WARN))

    try:
        search_opts = yt_dlp_opts.copy()
        if not is_search and ('list=' in query or 'playlist' in query):
            search_opts['noplaylist'] = False
            search_opts['extract_flat'] = 'in_playlist'
            search_opts['playliststart'] = start_idx
            search_opts['playlistend'] = end_idx

        with youtube_dl.YoutubeDL(search_opts) as ydl:
            info = await client.loop.run_in_executor(None, lambda: ydl.extract_info(query, download=False))
            if not info:
                if 'wait_msg' in locals(): await wait_msg.delete()
                return await ctx.send(embed=create_embed("❌ Lỗi", "Không tìm thấy dữ liệu.", COLOR_ERROR))
            if 'entries' in info:
                if is_search:
                    entries = [info['entries'][0]]
                else:
                    entries = [e for e in info['entries'] if e]
            else:
                entries = [info]

            songs_to_add = []
            for e in entries:
                if e:
                    webpage_url = e.get('url') or e.get('webpage_url')
                    if not webpage_url and e.get('id'): webpage_url = f"https://www.youtube.com/watch?v={e['id']}"
                    if webpage_url:
                        songs_to_add.append({'webpage_url': webpage_url, 'title': e.get('title', 'Unknown'),
                                             'duration': e.get('duration', 0), 'speed': 1.0, 'requester': ctx.author})
    except Exception as e:
        if 'wait_msg' in locals(): await wait_msg.delete()
        return await ctx.send(
            embed=create_embed("❌ Lỗi", "Lỗi nạp dữ liệu, thử lại bằng link/tên khác nhé.", COLOR_ERROR))

    if not songs_to_add:
        if 'wait_msg' in locals(): await wait_msg.delete()
        return await ctx.send(embed=create_embed("❌ Lỗi", "Không tìm thấy bài hát nào.", COLOR_ERROR))

    if ctx.guild.id not in queues: queues[ctx.guild.id] = []

    if getattr(ctx, 'playnext', False):
        for song in reversed(songs_to_add): queues[ctx.guild.id].insert(0, song)
        if len(songs_to_add) == 1:
            await ctx.send(
                embed=create_embed("🔼 Chèn Ưu Tiên", f"Đã kéo **{songs_to_add[0]['title']}** lên đầu!", COLOR_SUCCESS))
        else:
            await ctx.send(embed=create_embed("🔼 Chèn Ưu Tiên", f"Đã kéo **Playlist {len(songs_to_add)} bài** lên đầu!",
                                              COLOR_SUCCESS))
    else:
        queues[ctx.guild.id].extend(songs_to_add)
        if 'wait_msg' in locals(): await wait_msg.delete()
        if len(songs_to_add) == 1:
            await ctx.send(embed=discord.Embed(title="✅ Lên đơn thành công!",
                                               description=f"**[{songs_to_add[0]['title']}]({songs_to_add[0]['webpage_url']})**",
                                               color=COLOR_SUCCESS))
        else:
            playlist_title = info.get('title', 'Playlist') if 'entries' in info and not is_search else "Playlist"
            await ctx.send(embed=discord.Embed(title="✅ Đã nạp Playlist!",
                                               description=f"Đã thêm **{len(songs_to_add)}** bài hát từ **{playlist_title}** vào hàng đợi.",
                                               color=COLOR_SUCCESS))

    if ctx.voice_client and not ctx.voice_client.is_playing(): await start_playing(ctx)


@client.command(name='filter', help='🎛️ Bộ lọc âm thanh (bassboost, nightcore, vaporwave, clear)')
async def filter_cmd(ctx, effect: str = 'clear'):
    if effect not in ['bassboost', 'nightcore', 'vaporwave', 'clear']: return await ctx.send(
        embed=create_embed("❌ Bộ lọc không hợp lệ", "Chỉ hỗ trợ: `bassboost`, `nightcore`, `vaporwave`, `clear`",
                           COLOR_ERROR))
    audio_filters[ctx.guild.id] = effect
    if ctx.guild.id in now_playing and ctx.voice_client.is_playing():
        song = now_playing[ctx.guild.id]
        song['seeking'] = True
        song['target_seek'] = time.time() - song['start_time']
        song['announce_seek'] = True
        ctx.voice_client.stop()
    await ctx.send(
        embed=create_embed("🎛️ Audio Filter", f"Đã áp dụng hiệu ứng: **{effect.capitalize()}**", COLOR_SUCCESS))


@client.command(name='lyrics', help='📄 Lấy lời bài hát')
async def lyrics(ctx):
    if ctx.guild.id not in now_playing:
        return await ctx.send(embed=create_embed("❌ Ơ", "Có bài nào đang phát đâu mà đòi xem lời?", COLOR_ERROR))

    song_title = now_playing[ctx.guild.id]['title']
    wait_msg = await ctx.send(embed=create_embed("📄 Đang lật giấy tìm lời...",
                                                 f"Đang lục lọi đống giấy tờ để tìm lời cho bài: **{song_title}**",
                                                 COLOR_WARN))

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"https://lrclib.net/api/search?q={song_title}") as response:
                data = await response.json()
                if not data or len(data) == 0 or not data[0].get('plainLyrics'):
                    return await wait_msg.edit(
                        embed=create_embed("❌ Bó tay", "Bài này lật tung tờ giấy cũng không thấy lời 😿", COLOR_ERROR))

                lyric_text = data[0]['plainLyrics']
                if len(lyric_text) > 4000: lyric_text = lyric_text[:4000] + "..."

                lyric_embed = discord.Embed(title=f"📄 Lời bài hát: {song_title}", description=f"```\n{lyric_text}\n```",
                                            color=COLOR_MAIN)
                await wait_msg.edit(embed=lyric_embed)
    except:
        await wait_msg.edit(
            embed=create_embed("❌ Lỗi Mạng", "API tìm lời đang gặp sự cố, hãy thử lại sau!", COLOR_ERROR))


@client.command(name='search', help='🔎 Tìm kiếm và chọn bài hát (1-5)')
async def search(ctx, *, query: str):
    if not ctx.author.voice: return await ctx.send("❌ Chui vào Voice Channel đi bạn ơi!")
    wait_msg = await ctx.send(embed=create_embed("🔎 Đang cày cuốc...", "Đang mò 5 bài hát gần nhất...", COLOR_WARN))
    try:
        with youtube_dl.YoutubeDL(yt_dlp_opts) as ydl:
            info = await client.loop.run_in_executor(None,
                                                     lambda: ydl.extract_info(f"ytsearch5:{query}", download=False))
            entries = info.get('entries', [])
            if not entries: return await wait_msg.edit(
                embed=create_embed("❌ Lỗi", "Không có kết quả nào.", COLOR_ERROR))
            desc = "Gõ phím số từ **1** đến **5** để chọn bài nhé:\n\n"
            for i, e in enumerate(entries): desc += f"`{i + 1}.` **{e['title']}**\n"
            await wait_msg.edit(embed=discord.Embed(title="🔎 Kết Quả Tìm Kiếm", description=desc, color=COLOR_MAIN))

            def check(m):
                return m.author == ctx.author and m.channel == ctx.channel and m.content.isdigit()

            msg = await client.wait_for('message', check=check, timeout=30.0)
            idx = int(msg.content) - 1
            if idx < 0 or idx >= len(entries): return await ctx.send("❌ Sai số rồi bạn êi!")
            await play.callback(ctx, query=entries[idx]['webpage_url'])
    except asyncio.TimeoutError:
        await ctx.send("⏰ Hết giờ chọn bài!")
    except Exception as e:
        await ctx.send(f"❌ Lỗi: {e}")


@client.command(name='skipto', help='⏭️ Nhảy cóc đến bài hát số X')
async def skipto(ctx, index: int):
    if ctx.guild.id not in queues or len(queues[ctx.guild.id]) == 0: return await ctx.send("❌ Hàng đợi trống!")
    if index < 1 or index > len(queues[ctx.guild.id]): return await ctx.send("❌ Nhập số cho chuẩn vào!")
    song_to_play = queues[ctx.guild.id].pop(index - 1)
    queues[ctx.guild.id].insert(0, song_to_play)
    if ctx.voice_client and ctx.voice_client.is_playing(): ctx.voice_client.stop()
    await ctx.send(
        embed=create_embed("⏭️ Ưu Tiên Phát", f"Đã kéo bài **{song_to_play['title']}** lên phát ngay!", COLOR_SUCCESS))


@client.command(name='move', help='🔄 Di chuyển bài (A sang B)')
async def move(ctx, frm: int, to: int):
    q = queues.get(ctx.guild.id, [])
    if not q or frm < 1 or frm > len(q) or to < 1 or to > len(q): return await ctx.send(
        embed=create_embed("❌ Lỗi", "Vị trí không tồn tại.", COLOR_ERROR))
    song = q.pop(frm - 1)
    q.insert(to - 1, song)
    await ctx.send(
        embed=create_embed("🔄 Di chuyển", f"Đã dời **{song['title']}** sang vị trí **{to}**.", COLOR_SUCCESS))


@client.command(name='remove', help='🗑️ Xóa bài khỏi hàng đợi', aliases=['rm'])
async def remove(ctx, index: int):
    q = queues.get(ctx.guild.id, [])
    if not q or index < 1 or index > len(q): return await ctx.send(
        embed=create_embed("❌ Lỗi", "Số này không có trong hàng đợi.", COLOR_ERROR))
    removed = q.pop(index - 1)
    await ctx.send(embed=create_embed("🗑️ Đã xóa", f"Đã xóa **{removed['title']}**.", COLOR_SUCCESS))


@client.command(name='shuffle', help='🔀 Trộn ngẫu nhiên hàng đợi')
async def shuffle(ctx):
    if ctx.guild.id in queues and len(queues[ctx.guild.id]) > 1:
        random.shuffle(queues[ctx.guild.id])
        await ctx.send(embed=create_embed("🔀 Shazam!", "Đã trộn bài thành công!", COLOR_SUCCESS))
    else:
        await ctx.send(embed=create_embed("❌ Ơ kìa", "Hàng đợi chả có mấy bài thì trộn cái gì?", COLOR_ERROR))


@client.command(name='nowplaying', help='🎵 Hiện bảng điều khiển', aliases=['np'])
async def nowplaying(ctx):
    if ctx.guild.id not in now_playing: return await ctx.send("❌ Đang im ắng mà.")
    song = now_playing[ctx.guild.id]
    song['seeking'] = True
    song['target_seek'] = time.time() - song['start_time']
    song['announce_seek'] = True
    if ctx.voice_client.is_playing(): ctx.voice_client.stop()


@client.command(name='loop', help='🔁 Bật/tắt lặp nhạc')
async def loop_song(ctx):
    await ctx.send("💡 Tip: Hãy dùng nút 🔁 ở bảng điều khiển nhé!")


@client.command(name='pause', help='⏸️ Tạm dừng bài hát')
async def pause(ctx):
    if ctx.voice_client and ctx.voice_client.is_playing():
        ctx.voice_client.pause()
        await ctx.send(embed=create_embed("⏸️ Tạm Dừng", "Nghỉ ngơi xíu đã.", COLOR_WARN))


@client.command(name='resume', help='▶️ Tiếp tục bài hát', aliases=['r'])
async def resume(ctx):
    if ctx.voice_client and ctx.voice_client.is_paused():
        ctx.voice_client.resume()
        await ctx.send(embed=create_embed("▶️ Lên", "Quẩy tiếp thôi!", COLOR_SUCCESS))


@client.command(name='queue', help='📜 Xem sổ tay hàng đợi', aliases=['q'])
async def queue(ctx):
    embed = discord.Embed(title="🎶 Sổ Tay Hàng Đợi", color=COLOR_MAIN)
    if ctx.guild.id in queues and queues[ctx.guild.id]:
        desc = ""
        for i, song in enumerate(
            queues[ctx.guild.id][:10]): desc += f"`{i + 1}.` **[{song['title']}]({song['webpage_url']})**\n"
        if len(queues[ctx.guild.id]) > 10: desc += f"\n*...cùng với {len(queues[ctx.guild.id]) - 10} bài nữa.*"
        embed.description = desc
    else:
        embed.description = "Hàng đợi đang trống."
    await ctx.send(embed=embed)


@client.command(name='ping', help='🏓 Xem độ trễ')
async def ping(ctx):
    await ctx.send(embed=create_embed("🏓 Pong!", f"Độ trễ mượt mà: **{round(client.latency * 1000)}ms**", COLOR_MAIN))


client.run(TOKEN)
