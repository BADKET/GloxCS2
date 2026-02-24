import discord
from discord.ext import tasks, commands
import aiohttp
import json
import os
import datetime
import re
from dotenv import load_dotenv
from flask import Flask
from threading import Thread

# Flask server for 7/24 alive status
app = Flask('')

@app.route('/')
def home():
    return "Glox CS2 Bot is Alive!", 200

def run():
    port = int(os.getenv('PORT', 8080))
    try:
        app.run(host='0.0.0.0', port=port)
    except: pass

def keep_alive():
    t = Thread(target=run)
    t.start()

# Configuration
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("DUYURU_KANAL_ID"))
ADMIN_ID = int(os.getenv("ADMIN_ID"))
GUILD_ID = os.getenv("GUILD_ID")
STEAM_API_URL = "https://api.steampowered.com/ISteamNews/GetNewsForApp/v2/?appid=730&count=1"
DATA_FILE = "data.json"

# Settings
AUTO_SAFE_HOURS = 24 

def load_data():
    if not os.path.exists(DATA_FILE):
        return {"last_news_id": "0", "last_warning_message_id": None, "current_status": "SAFE", "fixed_id": None}
    try:
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    except:
        return {"last_news_id": "0", "last_warning_message_id": None, "current_status": "SAFE", "fixed_id": None}

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)

class CS2UpdateBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)
        self.data = load_data()
        self.first_run = True

    async def setup_hook(self):
        self.check_updates.start()
        try:
            if GUILD_ID:
                guild = discord.Object(id=int(GUILD_ID))
                self.tree.copy_global_to(guild=guild)
                await self.tree.sync(guild=guild)
        except: pass

    async def update_presence(self, status_mode):
        if status_mode == "RISKY":
            activity = discord.Activity(type=discord.ActivityType.watching, name="🔴 CS2: RISKY | discord.gg/fQUYJ4JXck")
            status = discord.Status.dnd
        else:
            activity = discord.Activity(type=discord.ActivityType.playing, name="🟢 CS2: SAFE | discord.gg/fQUYJ4JXck")
            status = discord.Status.online
        await self.change_presence(status=status, activity=activity)

    @tasks.loop(minutes=2)
    async def check_updates(self):
        await self.wait_until_ready()
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(STEAM_API_URL) as response:
                    if response.status == 200:
                        json_data = await response.json()
                        news_items = json_data.get("appnews", {}).get("newsitems", [])
                        if not news_items: return
                        
                        item = news_items[0]
                        news_id, news_title, news_url, news_content, news_ts = item.get("gid"), item.get("title"), item.get("url"), item.get("contents"), item.get("date")

                        # Content Cleaning (Regex ile tüm tagleri sil)
                        text = re.sub(r'<[^>]*?>', '', news_content) # HTML sil
                        text = re.sub(r'\[.*?\]', '', text) # BBCode [p], [list] vb sil
                        text = text.replace("MISC", "").replace("  ", " ").strip()
                        summary = (text[:297] + "...") if len(text) > 300 else text

                        # Security Check
                        is_sec = any(w in news_title.lower() or w in text.lower() for w in ["vac", "anti-cheat", "ac", "security", "detection"])
                        is_fresh = (datetime.datetime.now().timestamp() - news_ts) < (AUTO_SAFE_HOURS * 3600)

                        # Decision Logic
                        is_new_id = news_id != self.data["last_news_id"]
                        is_manually_fixed = self.data.get("fixed_id") == news_id
                        
                        target_status = "SAFE" if is_manually_fixed else ("RISKY" if (is_fresh or is_sec) else "SAFE")
                        status_changed = target_status != self.data.get("current_status")
                        
                        if is_new_id or status_changed or self.first_run:
                            should_send = is_new_id or status_changed or self.first_run
                            
                            self.data["current_status"] = target_status
                            self.data["last_news_id"] = news_id

                            channel = self.get_channel(CHANNEL_ID)
                            if channel and should_send:
                                if target_status == "SAFE":
                                    icon, color, msg = "「🟢」", 0x00ff7f, "✅ Systems stable. Security verification completed."
                                    if is_manually_fixed: msg = "✅ Verified by Admin. System is safe for use."
                                else:
                                    icon, color, msg = "「🔴」", 0x6a0dad, "⚠️ **WARNING:** New update detected. Security check in progress."
                                    if is_sec: icon, color, msg = "「💀」", 0xff0000, "🚨 **URGENT:** VAC/Anti-Cheat changes detected!"

                                embed = discord.Embed(title=f"{icon} {news_title}", url=news_url, description=f"{msg}\n\n**━━━━━━━━━━━━━━━━━━━━━━**", color=color, timestamp=datetime.datetime.fromtimestamp(news_ts))
                                embed.add_field(name="📡 Status", value=f"**`{target_status}`**", inline=True)
                                embed.add_field(name="🕒 Time", value=f"<t:{news_ts}:R>", inline=True)
                                embed.add_field(name="📝 Summary", value=f"```text\n{summary}\n```", inline=False)
                                embed.add_field(name="🔗 Link", value=f"➔ [Steam News Path]({news_url})", inline=False)
                                embed.set_footer(text="Glox CS2 Update Tracker")
                                
                                sent_msg = await channel.send(content="@everyone", embed=embed)
                                if target_status == "RISKY": self.data["last_warning_message_id"] = sent_msg.id
                                
                                await self.update_presence(target_status)
                                try: await channel.edit(name=f"{icon}cs2-update-tracker")
                                except: pass

                            self.first_run = False
                            save_data(self.data)
            except Exception as e: print(f"Error: {e}")

bot = CS2UpdateBot()

@bot.tree.command(name="status", description="Shows the current security status.")
async def status(interaction: discord.Interaction):
    s = bot.data.get("current_status", "SAFE")
    prefix = "「🟢」" if s == "SAFE" else "「🔴」"
    embed = discord.Embed(title=f"{prefix} GLOX-CS2 STATUS", color=0x00ff7f if s == "SAFE" else 0x6a0dad, timestamp=datetime.datetime.now())
    embed.add_field(name="🛡️ SECURITY STATUS", value=f"**`{s}`**", inline=False)
    embed.add_field(name="🧬 Last Update ID", value=f"`{bot.data.get('last_news_id')}`", inline=True)
    embed.add_field(name="🌐 Link", value="[Join Glox Discord](https://discord.gg/fQUYJ4JXck)", inline=False)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="test_vac", description="Simulates a VAC update.")
async def test_vac(interaction: discord.Interaction):
    if interaction.user.id != ADMIN_ID: return
    bot.data["fixed_id"] = None # Test için kilidi aç
    bot.first_run = True
    await interaction.response.send_message("Testing VAC scenario...", ephemeral=True)
    await bot.check_updates()

@bot.tree.command(name="fix", description="Sets the status to SAFE manually.")
async def fix(interaction: discord.Interaction):
    if interaction.user.id != ADMIN_ID: return
    
    # Bellekteki veriyi güncelle
    bot.data["fixed_id"] = bot.data.get("last_news_id")
    bot.data["current_status"] = "SAFE"
    save_data(bot.data)
    
    # Eski mesajı kanaldan sil
    channel = bot.get_channel(CHANNEL_ID)
    if channel and bot.data.get("last_warning_message_id"):
        try:
            m = await channel.fetch_message(bot.data["last_warning_message_id"])
            await m.delete()
            bot.data["last_warning_message_id"] = None
        except: pass
    
    await interaction.response.send_message("Updating announcement to SAFE status...", ephemeral=True)
    
    # Döngüyü anında tetikle (Zaten fixed_id olduğu için YEŞİL mesaj atacak)
    bot.first_run = True 
    await bot.check_updates()

if __name__ == "__main__":
    if TOKEN: keep_alive(); bot.run(TOKEN)
