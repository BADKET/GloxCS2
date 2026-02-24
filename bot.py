import discord
from discord.ext import tasks, commands
import aiohttp
import json
import os
import datetime
import re
import re
from dotenv import load_dotenv
from flask import Flask
from threading import Thread

# Flask sunucusu (Render vb. yerlerde 7/24 açık kalması için)
app = Flask('')

@app.route('/')
def home():
    # Render'ın "burada mısın?" sorusuna cevap
    print("Health check received!")
    return "Glox CS2 Bot is Alive!", 200

def run():
    port = int(os.getenv('PORT', 8080))
    print(f"Web server starting on port {port}...")
    try:
        app.run(host='0.0.0.0', port=port)
    except Exception as e:
        print(f"Web server failed: {e}")

def keep_alive():
    t = Thread(target=run)
    t.start()

# Load .env file
load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("DUYURU_KANAL_ID"))
ADMIN_ID = int(os.getenv("ADMIN_ID"))
GUILD_ID = os.getenv("GUILD_ID")
STEAM_API_URL = "https://api.steampowered.com/ISteamNews/GetNewsForApp/v2/?appid=730&count=1"
DATA_FILE = "data.json"

def load_data():
    if not os.path.exists(DATA_FILE):
        return {"last_news_id": "0", "last_warning_message_id": None, "current_status": "SAFE"}
    with open(DATA_FILE, "r") as f:
        return json.load(f)

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
        
        # Guild-specific sync (Instant)
        if GUILD_ID:
            guild = discord.Object(id=int(GUILD_ID))
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            print(f"INSTANT SYNC: {len(synced)} commands activated for this guild.")
        else:
            synced = await self.tree.sync()
            print(f"GLOBAL SYNC: {len(synced)} commands synced globally (may take up to 1 hour).")

    async def update_presence(self, status_mode):
        if status_mode == "RISKY":
            activity = discord.Activity(type=discord.ActivityType.watching, name="🔴 CS2: RISKY | discord.gg/fQUYJ4JXck")
            status = discord.Status.dnd
        else:
            activity = discord.Activity(type=discord.ActivityType.playing, name="🟢 CS2: SAFE | discord.gg/fQUYJ4JXck")
            status = discord.Status.online
        
        await self.change_presence(status=status, activity=activity)

    async def on_ready(self):
        print(f"---------------------------------")
        print(f"Bot Active: {self.user.name}")
        print(f"Guild ID: {GUILD_ID or 'Not set (Global mode)'}")
        print(f"---------------------------------")
        await self.update_presence(self.data.get("current_status", "SAFE"))

    @tasks.loop(minutes=2)
    async def check_updates(self):
        await self.wait_until_ready()
        
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(STEAM_API_URL) as response:
                    if response.status == 200:
                        json_data = await response.json()
                        news_items = json_data.get("appnews", {}).get("newsitems", [])
                        
                        if not news_items:
                            return
                        
                        latest_news = news_items[0]
                        news_id = latest_news.get("gid")
                        news_title = latest_news.get("title", "Unknown Update")
                        news_url = latest_news.get("url")
                        news_content = latest_news.get("contents", "")
                        news_timestamp = latest_news.get("date")

                        # --- Content Cleaning ---
                        text = re.sub(r'<[^>]*?>', '', news_content)
                        text = re.sub(r'\[.*?\]', '', text)
                        text = text.replace("MISC", "").replace("  ", " ").strip()
                        
                        if "Localization code and text changes" in text:
                            text = "🌐 Localization code and text changes."
                        
                        lines = [line.strip() for line in text.split('\n') if line.strip()]
                        clean_text = "\n".join(lines)
                        summary = clean_text if len(clean_text) <= 300 else clean_text[:297] + "..."
                        # -------------------------

                        security_keywords = ["vac", "anti-cheat", "ac", "security", "module", "signature", "authenticator", "trust factor", "detection"]
                        is_security_update = any(word in news_title.lower() or word in text.lower() for word in security_keywords)

                        now_ts = datetime.datetime.now().timestamp()
                        update_age_seconds = now_ts - news_timestamp
                        is_fresh_update = update_age_seconds < (24 * 3600)

                        if news_id != self.data["last_news_id"] or self.first_run:
                            is_new_discovery = news_id != self.data["last_news_id"]
                            self.data["last_news_id"] = news_id
                            
                            if is_fresh_update or is_security_update:
                                self.data["current_status"] = "RISKY"
                                if is_security_update:
                                    alert_color = 0xff0000 
                                    status_text = "💀 CRITICAL RISK (VAC)"
                                    alert_msg = "🚨 **URGENT:** VAC/Anti-Cheat changes detected! DO NOT use the cheat until verified."
                                else:
                                    alert_color = 0x6a0dad 
                                    status_text = "🔴 RISKY / DO NOT USE"
                                    alert_msg = "⚠️ **WARNING:** New update detected. Security check is in progress."
                            else:
                                self.data["current_status"] = "SAFE"
                                alert_color = 0x2f3136 
                                status_text = "🟢 UPDATED / SAFE"
                                alert_msg = "ℹ️ Systems stable. No recent critical updates detected."

                            channel = self.get_channel(CHANNEL_ID)
                            if channel:
                                embed = discord.Embed(
                                    title=f"{'「💀」' if is_security_update else '「🔴」'} {news_title}",
                                    url=news_url,
                                    description=f"{alert_msg}\n\n**━━━━━━━━━━━━━━━━━━━━━━**",
                                    color=alert_color,
                                    timestamp=datetime.datetime.fromtimestamp(news_timestamp)
                                )
                                
                                if is_security_update:
                                    embed.add_field(
                                        name="🛡️ SECURITY ANALYSIS", 
                                        value="> This update may target anti-cheat systems. **Strictly not recommended to login.**", 
                                        inline=False
                                    )

                                embed.add_field(name="📡 Status", value=f"**`{status_text}`**", inline=True)
                                embed.add_field(name="🕒 Time", value=f"<t:{news_timestamp}:R>", inline=True)
                                
                                embed.add_field(
                                    name="📝 Patch Notes Summary", 
                                    value=f"```text\n{summary or 'No details provided.'}\n```", 
                                    inline=False
                                )
                                
                                embed.add_field(name="🔗 Links", value=f"[➔ Steam News Path]({news_url})", inline=False)
                                embed.set_footer(text="Glox CS2 Update Tracker • High-End Monitoring")
                                
                                content = "@everyone" if (is_new_discovery and (is_fresh_update or is_security_update)) else None
                                msg = await channel.send(content=content, embed=embed)
                                
                                if is_fresh_update or is_security_update:
                                    self.data["last_warning_message_id"] = msg.id
                                
                                await self.update_presence(self.data["current_status"])
                                
                                # Kanal ismini güncelle
                                try:
                                    channel_prefix = "「💀」" if is_security_update else "「🔴」"
                                    await channel.edit(name=f"{channel_prefix}-cs2-duyuru")
                                except Exception as e:
                                    print(f"Kanal ismi güncellenemedi (Limit olabilir): {e}")

                                self.first_run = False
                                save_data(self.data)
                    else:
                        print(f"Steam API Error: {response.status}")
            except Exception as e:
                print(f"Error occurred: {e}")

bot = CS2UpdateBot()

@bot.tree.command(name="status", description="Shows the current security status of the CS2 cheat.")
async def status(interaction: discord.Interaction):
    data = load_data()
    status_val = data.get("current_status", "SAFE")
    last_id = data.get("last_news_id", "Unknown")
    
    if status_val == "RISKY":
        color = 0x6a0dad 
        status_text = "「🔴」 RISKY / DO NOT USE"
        desc = "⚠️ Game version changed. Security scan in progress, please wait."
        prefix = "「🔴」"
    else:
        color = 0x00ff7f 
        status_text = "「🟢」 UPDATED / SAFE"
        desc = "✅ Systems active. Cheat is fully compatible with the current version."
        prefix = "「🟢」"

    embed = discord.Embed(
        title=f"{prefix} GLOX-CS2 STATUS",
        description=f"{desc}\n\n**━━━━━━━━━━━━━━━━━━━━━━**",
        color=color,
        timestamp=datetime.datetime.now()
    )
    
    embed.add_field(name="🛡️ SECURITY STATUS", value=f"**`{status_text}`**", inline=False)
    embed.add_field(name="🧬 Version ID", value=f"`{last_id}`", inline=True)
    embed.add_field(name="📡 Monitoring", value="`ACTIVE` ✅", inline=True)
    embed.add_field(name="🌐 Community", value="[Join Glox Discord](https://discord.gg/fQUYJ4JXck)", inline=False)
    
    embed.set_footer(text=f"Requested by: {interaction.user.name}", icon_url=interaction.user.avatar.url if interaction.user.avatar else None)
    
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="test_vac", description="Simulates a VAC update scenario.")
async def test_vac(interaction: discord.Interaction):
    if interaction.user.id != ADMIN_ID:
        await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)
        return

    await interaction.response.send_message("Starting VAC Test scenario...", ephemeral=True)
    channel = bot.get_channel(CHANNEL_ID)
    if not channel: return

    news_title = "Release Notes for 2/24/2026 (VAC Live Update)"
    news_url = "https://store.steampowered.com/news/app/730"
    news_timestamp = int(datetime.datetime.now().timestamp())
    clean_content = "+ Added new VAC Live detection modules.\n- Fixed exploit related to sub-tick movement.\n* Security signatures have been updated."
    
    embed = discord.Embed(
        title=f"「💀」 {news_title}",
        url=news_url,
        description="🚨 **URGENT:** VAC/Anti-Cheat changes detected! DO NOT use the cheat until verified.\n\n**━━━━━━━━━━━━━━━━━━━━━━**",
        color=0xff0000,
        timestamp=datetime.datetime.fromtimestamp(news_timestamp)
    )
    
    embed.add_field(name="🛡️ SECURITY ANALYSIS", value="> This update may target anti-cheat systems. **Strictly not recommended to login.**", inline=False)
    embed.add_field(name="📡 Status", value="**`「💀」 CRITICAL RISK (VAC)`**", inline=True)
    embed.add_field(name="🕒 Time", value=f"<t:{news_timestamp}:R>", inline=True)
    embed.add_field(name="📝 Patch Notes Summary", value=f"```text\n{clean_content}\n```", inline=False)
    embed.set_footer(text="Glox CS2 Update Tracker • Test Mode")
    
    await channel.send(content="@everyone", embed=embed)
    # Test amaçlı profil durumunu da RİSKLİ yap
    await bot.update_presence("RISKY")
    # Kanal ismini güncelle
    try:
        await channel.edit(name="「💀」-cs2-duyuru")
    except: pass

@bot.tree.command(name="fix", description="Sets the cheat to safe mode and makes a detailed announcement.")
async def fix(interaction: discord.Interaction):
    if interaction.user.id != ADMIN_ID:
        await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)
        return

    data = load_data()
    data["current_status"] = "SAFE"
    channel = bot.get_channel(CHANNEL_ID)
    if not channel: return
    
    if data["last_warning_message_id"]:
        try:
            msg = await channel.fetch_message(data["last_warning_message_id"])
            await msg.delete()
        except: pass
        data["last_warning_message_id"] = None

    embed = discord.Embed(
        title="「�」 GLOX-CS2 SECURITY VERIFIED",
        description="Latest version analysis completed and components verified.",
        color=0x00ff7f,
        timestamp=datetime.datetime.now()
    )
    
    embed.add_field(name="📊 Analysis Status", value="> `VAC / Anti-Cheat Scanned` ✅\n> `Signature Check Done` ✅\n> `Server Tests Passed` ✅", inline=False)
    embed.add_field(name="🛰️ Current Status", value="**`「🟢」 UPDATED / SAFE`**", inline=True)
    embed.add_field(name="🕒 Verification Time", value=f"<t:{int(datetime.datetime.now().timestamp())}:R>", inline=True)
    embed.add_field(name="🎮 Entry Status", value="**✅ You can safely enter the game.**\nAll features are active and stable.", inline=False)
    embed.set_footer(text="Glox Digital Security • All Systems Active")
    
    await channel.send(content="@everyone", embed=embed)
    await interaction.response.send_message("Status updated to SAFE and announcement sent.", ephemeral=True)
    await bot.update_presence("SAFE")
    # Kanal ismini tekrar yeşile çek
    try:
        await channel.edit(name="「🟢」-cs2-duyuru")
    except: pass
    save_data(data)

if __name__ == "__main__":
    if TOKEN:
        keep_alive() # Web sunucusunu başlat
        bot.run(TOKEN)
    else:
        print("Please fill in the DISCORD_TOKEN in the .env file!")
