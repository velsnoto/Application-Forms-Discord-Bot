import discord
from discord.ext import commands
from discord import app_commands
import json
import os
import smtplib
from email.message import EmailMessage
import threading
from flask import Flask, render_template, request, jsonify
import uuid
import asyncio

import os

# --- CONFIGURATION ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TOKEN = "I'm not giving you my discord bot token lmfao. "
APPLICATION_CHANNEL_ID = 1501525887089250324

# Email config (User needs to fill this out)
SENDER_EMAIL = "add ur gmail you want to send the no-reply thingys off"
SENDER_PASSWORD = "ur gmail app password"

app = Flask(__name__, template_folder=os.path.join(BASE_DIR, "templates"))

# Intents and bot setup
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# Database files
APPS_FILE = os.path.join(BASE_DIR, "applications.json")
BLACKLIST_FILE = os.path.join(BASE_DIR, "blacklist.json")

def load_json(filename):
    if not os.path.exists(filename):
        return {}
    try:
        with open(filename, "r") as f:
            content = f.read().strip()
            if not content:
                return {}
            return json.loads(content)
    except Exception as e:
        print(f"Error loading {filename}: {e}")
        return {}

def save_json(filename, data):
    with open(filename, "w") as f:
        json.dump(data, f, indent=4)

# Load databases
applications = load_json(APPS_FILE)
blacklist = load_json(BLACKLIST_FILE)

def send_email(to_email, subject, body):
    if SENDER_EMAIL == "add ur gmail you want to send the no-reply thingys off":
        print("WARNING: Email not sent. Please configure SENDER_EMAIL and SENDER_PASSWORD.")
        return False
    
    try:
        msg = EmailMessage()
        msg.set_content(body)
        msg['Subject'] = subject
        msg['From'] = SENDER_EMAIL
        msg['To'] = to_email

        server = smtplib.SMTP_SSL('smtp.gmail.com', 465)
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        server.send_message(msg)
        server.quit()
        return True
    except Exception as e:
        print(f"Failed to send email to {to_email}: {e}")
        return False

# --- FLASK APP ---

@app.route("/")
def form():
    return render_template("application_form.html")

@app.route("/submit", methods=["POST"])
def submit():
    full_name = request.form.get("full_name")
    mc_username = request.form.get("mc_username")
    gmail = request.form.get("gmail")
    year_group = request.form.get("year_group")
    school = request.form.get("school")
    reason = request.form.get("reason")
    

    global blacklist
    blacklist = load_json(BLACKLIST_FILE) 
    if mc_username in blacklist or gmail in blacklist:
        return "You are blacklisted from submitting applications.", 403

    app_id = str(uuid.uuid4())[:8].upper() 
    
    application_data = {
        "id": app_id,
        "full_name": full_name,
        "mc_username": mc_username,
        "gmail": gmail,
        "year_group": year_group,
        "school": school,
        "reason": reason,
        "status": "pending"
    }
    
    global applications
    applications = load_json(APPS_FILE)
    applications[app_id] = application_data
    save_json(APPS_FILE, applications)
    

    asyncio.run_coroutine_threadsafe(notify_discord(application_data), bot.loop)
    
    return "Application submitted successfully! You will receive an email shortly regarding your status."

async def notify_discord(data):
    channel = bot.get_channel(APPLICATION_CHANNEL_ID)
    if channel:
        embed = discord.Embed(title=f"New Application: {data['id']}", color=discord.Color.blue())
        embed.add_field(name="Full Name", value=data["full_name"], inline=True)
        embed.add_field(name="Minecraft Username", value=data["mc_username"], inline=True)
        embed.add_field(name="Gmail", value=data["gmail"], inline=False)
        embed.add_field(name="Year Group", value=data["year_group"], inline=True)
        embed.add_field(name="School", value=data["school"], inline=True)
        embed.add_field(name="Reason", value=data["reason"], inline=False)
        embed.set_footer(text=f"Use /accept {data['id']} or /decline {data['id']} <reason>")
        await channel.send(embed=embed)

def run_flask():
    app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)


@bot.event
async def on_ready():
    print(f'Bot connected as {bot.user}')
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s)")
    except Exception as e:
        print(e)

@bot.tree.command(name="accept", description="Accept an application and send a 1-day invite link.")
@app_commands.describe(app_id="The ID of the application to accept")
async def accept(interaction: discord.Interaction, app_id: str):
    global applications
    applications = load_json(APPS_FILE)
    
    if app_id not in applications:
        await interaction.response.send_message(f"Application ID `{app_id}` not found.", ephemeral=True)
        return
        
    if applications[app_id]["status"] != "pending":
        await interaction.response.send_message(f"Application `{app_id}` is already {applications[app_id]['status']}.", ephemeral=True)
        return

    # Create 1-day 1-use invite
    try:
        invite = await interaction.channel.create_invite(max_age=86400, max_uses=1, unique=True, reason=f"Accepted application {app_id}")
    except Exception as e:
        await interaction.response.send_message(f"Failed to create invite: {e}", ephemeral=True)
        return
        
    # Send Email
    subject = "Minecraft Server Application Accepted"
    body = f"Congratulations!\n\nYour application to the Minecraft server has been accepted.\n\nHere is your invite link: {invite.url}\n\nNote: This link will expire in 24 hours and can only be used once."
    
    email_sent = send_email(applications[app_id]["gmail"], subject, body)
    
    if email_sent:
        applications[app_id]["status"] = "accepted"
        save_json(APPS_FILE, applications)
        await interaction.response.send_message(f"Accepted `{app_id}`. Email sent with invite: {invite.url}")
    else:
        # If email config isn't set, still accept them in DB but note that email failed
        applications[app_id]["status"] = "accepted"
        save_json(APPS_FILE, applications)
        await interaction.response.send_message(f"Accepted `{app_id}` in DB, but failed to send email (check console). Invite link generated: {invite.url}")

@bot.tree.command(name="decline", description="Decline an application with a reason.")
@app_commands.describe(app_id="The ID of the application to decline", reason="The reason for declining")
async def decline(interaction: discord.Interaction, app_id: str, reason: str):
    global applications
    applications = load_json(APPS_FILE)
    
    if app_id not in applications:
        await interaction.response.send_message(f"Application ID `{app_id}` not found.", ephemeral=True)
        return
        
    if applications[app_id]["status"] != "pending":
        await interaction.response.send_message(f"Application `{app_id}` is already {applications[app_id]['status']}.", ephemeral=True)
        return

    # Send Email
    subject = "Minecraft Server Application Declined"
    body = f"Hello,\n\nUnfortunately, your application to the Minecraft server has been declined.\n\nReason: {reason}"
    
    email_sent = send_email(applications[app_id]["gmail"], subject, body)
    
    if email_sent:
        applications[app_id]["status"] = "declined"
        save_json(APPS_FILE, applications)
        await interaction.response.send_message(f"Declined `{app_id}`. Email sent with reason: {reason}")
    else:
        applications[app_id]["status"] = "declined"
        save_json(APPS_FILE, applications)
        await interaction.response.send_message(f"Declined `{app_id}` in DB, but failed to send email (check console).")

@bot.tree.command(name="blacklist", description="Blacklist a Minecraft username or Gmail address.")
@app_commands.describe(identifier="The Minecraft username or Gmail to blacklist")
async def blacklist_cmd(interaction: discord.Interaction, identifier: str):
    global blacklist
    blacklist = load_json(BLACKLIST_FILE)
    
    if identifier in blacklist:
        await interaction.response.send_message(f"`{identifier}` is already blacklisted.", ephemeral=True)
        return
        
    blacklist[identifier] = True
    save_json(BLACKLIST_FILE, blacklist)
    
    await interaction.response.send_message(f"Successfully blacklisted `{identifier}`.")

if __name__ == "__main__":
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    
    bot.run(TOKEN)
