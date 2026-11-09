# mini_bot.py: edit the settings below, then run: python3 mini_bot.py
# Install first: pip3 install discord.py
import asyncio, sqlite3, datetime as dt
import discord
from discord import app_commands

# ---------------- SETTINGS (edit these) ----------------
TOKEN = "MTU2NzMyMzExNDI2MDY2MDIyNA.GMtX1z.VMurhGJuB-bwfl1maAPTJrsG1dX-CHyONGYRQQ"
UPLINE_ID = 717823754545397830   # your Discord user ID (right-click yourself > Copy User ID)
GUILD_ID = 1518442289263804446    # your server ID (right-click server > Copy Server ID)
PARTNER_ID = 430816851245793282                   # your partner's Discord user ID (same upline # Starting values only. After the first run, change them in Discord with /setcomp, /setdefault, /setadvance.
YOUR_PCT = 110                   # your contract level %
AGENT_PCT = 60                   # default level for agents you haven't set
ADVANCE_MONTHS = 9               # months of advance
TEAM_GOAL_AP = 100000             # monthly team AP goal shown on the leaderboard (0 = hide)
BIG_CLOSE_AP = 3000              # closes at or above this AP get the "BIG CLOSE" look
# --------------------------------------------------------
 
db = sqlite3.connect("crm.db")
db.execute("""CREATE TABLE IF NOT EXISTS closes(
    id INTEGER PRIMARY KEY AUTOINCREMENT, uid INTEGER, name TEXT, client TEXT,
    ap REAL, coverage TEXT, carrier TEXT, ts TEXT)""")
db.execute("CREATE TABLE IF NOT EXISTS comp(uid INTEGER PRIMARY KEY, pct REAL)")
db.execute("CREATE TABLE IF NOT EXISTS settings(k TEXT PRIMARY KEY, v REAL)")
db.execute("CREATE TABLE IF NOT EXISTS channels(k TEXT PRIMARY KEY, channel_id TEXT, message_id TEXT)")
try:  # track which closes you've already paid out (added later, so upgrade old databases)
    db.execute("ALTER TABLE closes ADD COLUMN paid INTEGER DEFAULT 0")
except sqlite3.OperationalError:
    pass
db.execute("INSERT OR IGNORE INTO settings VALUES('default_pct', ?)", (AGENT_PCT,))
db.execute("INSERT OR IGNORE INTO settings VALUES('advance', ?)", (ADVANCE_MONTHS,))
db.execute("INSERT OR IGNORE INTO comp VALUES(?, ?)", (UPLINE_ID, YOUR_PCT))
db.commit()
 
# latest name an agent typed on a close, so the board always shows their current name
NAME_SQL = "(SELECT c2.name FROM closes c2 WHERE c2.uid=closes.uid ORDER BY c2.id DESC LIMIT 1)"
 
 
def setting(k): return db.execute("SELECT v FROM settings WHERE k=?", (k,)).fetchone()[0]
def level(uid):
    r = db.execute("SELECT pct FROM comp WHERE uid=?", (uid,)).fetchone()
    return r[0] if r else setting("default_pct")
 
def num(s): return float(s.replace("$", "").replace(",", "").strip())
def usd(n): return f"${n:,.0f}"
def cov_fmt(s):
    try: return usd(num(s))
    except ValueError: return s
def bar(v, mx, n=10):
    filled = round(n * v / mx) if mx else 0
    return "▰" * filled + "▱" * (n - filled)
def month_start(): return dt.datetime.now().replace(day=1, hour=0, minute=0, second=0).isoformat()
 
 
# ---------------- boards (the embeds that live in their own channels) ----------------
def build_leaderboard_embed():
    start = month_start()
    rows = db.execute(f"SELECT {NAME_SQL}, SUM(ap), COUNT(*) FROM closes WHERE ts>=? GROUP BY uid "
                      "ORDER BY SUM(ap) DESC LIMIT 10", (start,)).fetchall()
    total_ap, total_n = db.execute("SELECT COALESCE(SUM(ap),0), COUNT(*) FROM closes WHERE ts>=?", (start,)).fetchone()
    month = dt.datetime.now().strftime("%B").upper()
    e = discord.Embed(title=f"🏆  {month} LEADERBOARD  🏆", color=discord.Color.gold(),
                      timestamp=dt.datetime.now(dt.timezone.utc))
    if not rows:
        e.description = "No closes yet. Be the first on the board! 💪"
    else:
        medals = ["🥇", "🥈", "🥉"]
        top = rows[0][1]
        blocks = []
        for n, r in enumerate(rows):
            rank = medals[n] if n < 3 else f"`#{n+1}`"
            blocks.append(f"{rank} **{r[0]}**\n{bar(r[1], top)}  **{usd(r[1])}** AP · {r[2]} close{'s' if r[2] != 1 else ''}")
        e.description = "\n\n".join(blocks)
        if TEAM_GOAL_AP:
            pct = min(total_ap / TEAM_GOAL_AP, 1)
            e.add_field(name="🎯  Team Goal",
                        value=f"{bar(total_ap, TEAM_GOAL_AP, 15)}  **{usd(total_ap)}** / {usd(TEAM_GOAL_AP)}  ({pct:.0%})",
                        inline=False)
    e.set_footer(text=f"Team total: {usd(total_ap)} AP · {total_n} closes · updates live")
    return e
 
 
def build_payout_embed():
    rows = db.execute(f"SELECT uid, {NAME_SQL}, SUM(ap) FROM closes WHERE ts>=? GROUP BY uid ORDER BY SUM(ap) DESC",
                      (month_start(),)).fetchall()
    adv, mine = setting("advance") / 12, level(UPLINE_ID)
    table, override_total, personal_total, owed_total = [], 0.0, 0.0, 0.0
    for uid, name, ap in rows:
        n = (name or "?")[:14]
        if uid == UPLINE_ID:
            earn = ap * mine / 100 * adv
            personal_total += earn
            table.append(f"{n[:9] + ' (you)':<14} {mine:>4g}% {usd(ap):>8} {'-':>9} {usd(earn):>9}")
        else:
            pct = level(uid)
            owed = ap * pct / 100 * adv                    # what you pay the agent
            earn = ap * max(mine - pct, 0) / 100 * adv     # what you keep (override)
            owed_total += owed
            override_total += earn
            table.append(f"{n:<14} {pct:>4g}% {usd(ap):>8} {usd(owed):>9} {usd(earn):>9}")
    kept = override_total + personal_total
    head = f"{'AGENT':<14} {'LVL':>5} {'AP':>8} {'PAY THEM':>9} {'YOU KEEP':>9}"
    total_ap = sum(r[2] for r in rows)
    foot = f"{'TOTAL':<14} {'':>5} {usd(total_ap):>8} {usd(owed_total):>9} {usd(kept):>9}"
    body = "\n".join([head, "-" * len(head)] + table + ["-" * len(head), foot]) if table else "No closes yet."
    month = dt.datetime.now().strftime("%B").upper()
    summary = (f"💰 **You keep: {usd(kept)}**\n"
               f"└ override {usd(override_total)} + your own closes {usd(personal_total)}\n\n"
               f"💸 **Owed to downline: {usd(owed_total)}**\n\n"
               f"🏦 **Total from carriers: {usd(owed_total + kept)}**")
    e = discord.Embed(title=f"💼  PAYOUT: {month}", description=f"{summary}\n\n```\n{body}\n```",
                      color=discord.Color.green(), timestamp=dt.datetime.now(dt.timezone.utc))
    e.set_footer(text=f"Your level {mine:g}% · advance {setting('advance'):g} months · updates live")
    return e
 
 
def build_clients_embed():
    """Every client you still need to pay a downline agent for, grouped by agent."""
    adv, mine = setting("advance") / 12, level(UPLINE_ID)
    rows = db.execute("SELECT id, uid, name, client, ap, ts FROM closes "
                      "WHERE COALESCE(paid,0)=0 AND uid != ? ORDER BY uid, id", (UPLINE_ID,)).fetchall()
    groups, order = {}, []
    for cid, uid, name, client, ap, ts in rows:
        if uid not in groups:
            groups[uid] = []
            order.append(uid)
        groups[uid].append((cid, name, client, ap, ts))
    blocks, total_owed = [], 0.0
    for uid in order:
        pct = level(uid)
        items = groups[uid]
        sub = sum(r[3] for r in items) * pct / 100 * adv
        total_owed += sub
        lines = []
        for cid, name, client, ap, ts in items:
            d = dt.datetime.fromisoformat(ts)
            lines.append(f"`#{cid}` {client[:24]} · {usd(ap)} AP → **{usd(ap * pct / 100 * adv)}** · {d.strftime('%b')} {d.day}")
        blocks.append(f"### {items[-1][1]} @ {pct:g}% · owe {usd(sub)}\n" + "\n".join(lines))
    text, left = "", len(blocks)
    for b in blocks:
        if len(text) + len(b) > 3600:
            text += f"\n…and {left} more agent(s). Use `/clients` for the full list."
            break
        text += b + "\n\n"
        left -= 1
    paid_rows = db.execute("SELECT uid, ap FROM closes WHERE paid=1 AND uid != ? AND ts>=?",
                           (UPLINE_ID, month_start())).fetchall()
    paid_total = sum(ap * level(uid) / 100 * adv for uid, ap in paid_rows)
    if rows:
        head = (f"💸 **Still to pay out: {usd(total_owed)}** across {len(rows)} close{'s' if len(rows) != 1 else ''}\n"
                f"✅ Paid out this month: {usd(paid_total)}\n\n")
    else:
        head = f"✅ **Everyone is paid out.** Nothing owed right now.\nPaid out this month: {usd(paid_total)}"
    e = discord.Embed(title="📋  CLIENTS TO PAY OUT", description=head + text,
                      color=discord.Color.orange(), timestamp=dt.datetime.now(dt.timezone.utc))
    e.set_footer(text="After paying: /paid <close #> · /paidagent @agent · undo with /unpaid <close #>")
    return e
 
 
async def refresh_boards():
    """Edit the live leaderboard / comp / client-list messages after anything changes."""
    for key, builder in (("leaderboard", build_leaderboard_embed), ("comp", build_payout_embed),
                         ("clients", build_clients_embed)):
        row = db.execute("SELECT channel_id, message_id FROM channels WHERE k=?", (key,)).fetchone()
        if not row:
            continue
        try:
            ch = bot.get_channel(int(row[0])) or await bot.fetch_channel(int(row[0]))
            try:
                await ch.get_partial_message(int(row[1])).edit(embed=builder())
            except discord.NotFound:
                msg = await ch.send(embed=builder())
                db.execute("UPDATE channels SET message_id=? WHERE k=?", (str(msg.id), key))
                db.commit()
        except Exception as ex:
            print(f"Could not refresh {key} board:", ex)
 
 
# ---------------- close form ----------------
class CloseForm(discord.ui.Modal, title="Log a Close"):
    agent = discord.ui.TextInput(label="Your name (agent)", max_length=40)
    client = discord.ui.TextInput(label="Client name")
    ap = discord.ui.TextInput(label="AP (annual premium)", placeholder="1200")
    cov = discord.ui.TextInput(label="Coverage (face amount)", placeholder="250000")
    carrier = discord.ui.TextInput(label="Carrier / product", placeholder="Mutual of Omaha / IUL")
 
    def __init__(self, default_name=""):
        super().__init__()
        self.agent.default = default_name
 
    async def on_submit(self, i: discord.Interaction):
        try:
            ap = num(self.ap.value)
        except ValueError:
            return await i.response.send_message("AP must be a number, like 1200. Try again.", ephemeral=True)
        name = self.agent.value.strip() or i.user.display_name
        cur = db.execute("INSERT INTO closes(uid,name,client,ap,coverage,carrier,ts) VALUES(?,?,?,?,?,?,?)",
                   (i.user.id, name, self.client.value, ap, self.cov.value,
                    self.carrier.value, dt.datetime.now().isoformat()))
        db.commit()
        month_ap = db.execute("SELECT SUM(ap) FROM closes WHERE uid=? AND ts>=?",
                              (i.user.id, month_start())).fetchone()[0] or 0
        big = ap >= BIG_CLOSE_AP
        e = discord.Embed(title="🔥  BIG CLOSE  🔥" if big else "💰  NEW CLOSE",
                          color=discord.Color.gold() if big else discord.Color.green(),
                          timestamp=dt.datetime.now(dt.timezone.utc))
        e.set_author(name=name, icon_url=i.user.display_avatar.url)
        e.set_thumbnail(url=i.user.display_avatar.url)
        e.add_field(name="🧑‍💼  Closed by", value=f"**{name}**", inline=False)
        e.add_field(name="💵  AP", value=f"## {usd(ap)}", inline=True)
        e.add_field(name="🛡️  Coverage", value=f"## {cov_fmt(self.cov.value)}", inline=True)
        e.add_field(name="👤  Client", value=self.client.value, inline=False)
        e.set_footer(text=f"Close #{cur.lastrowid} · {name} is at {usd(month_ap)} AP this month")
        await i.response.send_message(content=f"🎉 Congrats {i.user.mention}!", embed=e)
        await refresh_boards()
 
 
class LogButton(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)
    @discord.ui.button(label="Log a Close", style=discord.ButtonStyle.success, custom_id="logclose")
    async def b(self, i: discord.Interaction, _): await i.response.send_modal(CloseForm(i.user.display_name))
 
 
class Bot(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.default())
        self.tree = app_commands.CommandTree(self)
    async def setup_hook(self):
        self.add_view(LogButton())
        g = discord.Object(id=GUILD_ID)
        self.tree.copy_global_to(guild=g)
        await self.tree.sync(guild=g)
 
bot = Bot(); tree = bot.tree
 
STICKY_TEXT = "## 💰 Log your close\nHit the button below 👇"
sticky_lock = asyncio.Lock()
 
 
@bot.event
async def on_message(m: discord.Message):
    """Keep the Log a Close button at the bottom of its channel."""
    if m.guild is None or (m.author == bot.user and m.components):
        return  # DMs, and the button message itself, are ignored
    row = db.execute("SELECT channel_id, message_id FROM channels WHERE k='sticky'").fetchone()
    if not row or str(m.channel.id) != row[0]:
        return
    async with sticky_lock:
        await asyncio.sleep(1)  # let a burst of messages settle
        row = db.execute("SELECT channel_id, message_id FROM channels WHERE k='sticky'").fetchone()
        try:
            await m.channel.get_partial_message(int(row[1])).delete()
        except discord.HTTPException:
            pass
        try:
            new = await m.channel.send(STICKY_TEXT, view=LogButton())
        except discord.HTTPException as ex:
            return print("Could not repost button:", ex)
        db.execute("UPDATE channels SET message_id=? WHERE k='sticky'", (str(new.id),))
        db.commit()
 
 
UPLINE_IDS = {UPLINE_ID, PARTNER_ID} - {0}   # everyone with upline powers
def upline_only(i): return i.user.id in UPLINE_IDS
 
 
# ---------------- everyone ----------------
@tree.command(name="close", description="Log a close")
async def close(i: discord.Interaction):
    await i.response.send_modal(CloseForm(i.user.display_name))
 
@tree.command(name="leaderboard", description="Top producers by AP this month")
async def leaderboard(i: discord.Interaction):
    await i.response.send_message(embed=build_leaderboard_embed())
 
 
# ---------------- upline only ----------------
@tree.command(name="setup", description="(Upline) Post the Log a Close button here")
async def setup(i: discord.Interaction):
    if not upline_only(i): return await i.response.send_message("Upline only.", ephemeral=True)
    await i.response.defer(ephemeral=True)
    old = db.execute("SELECT channel_id, message_id FROM channels WHERE k='sticky'").fetchone()
    if old:  # remove the previous button so there is only one
        try:
            oc = bot.get_channel(int(old[0])) or await bot.fetch_channel(int(old[0]))
            await oc.get_partial_message(int(old[1])).delete()
        except Exception:
            pass
    try:
        msg = await i.channel.send(STICKY_TEXT, view=LogButton())
    except discord.Forbidden:
        return await i.followup.send("I can't post in this channel. Give the bot access to it, then try again.", ephemeral=True)
    db.execute("INSERT INTO channels VALUES('sticky',?,?) ON CONFLICT(k) DO UPDATE SET "
               "channel_id=excluded.channel_id, message_id=excluded.message_id", (str(i.channel.id), str(msg.id)))
    db.commit()
    await i.followup.send("Done. The Log a Close button now stays at the bottom of this channel.", ephemeral=True)
 
 
async def make_board(i: discord.Interaction, key: str, builder, label: str):
    if not upline_only(i): return await i.response.send_message("Upline only.", ephemeral=True)
    await i.response.defer(ephemeral=True)
    try:
        msg = await i.channel.send(embed=builder())
    except discord.Forbidden:
        return await i.followup.send("I can't post in this channel. Give the bot access to it "
                                     "(channel settings > Permissions > add the bot), then try again.", ephemeral=True)
    db.execute("INSERT INTO channels VALUES(?,?,?) ON CONFLICT(k) DO UPDATE SET "
               "channel_id=excluded.channel_id, message_id=excluded.message_id",
               (key, str(i.channel.id), str(msg.id)))
    db.commit()
    await i.followup.send(f"Done. The {label} lives here now and updates itself after every close.", ephemeral=True)
 
 
@tree.command(name="setleaderboard", description="(Upline) Make THIS channel the live leaderboard")
async def setleaderboard(i: discord.Interaction):
    await make_board(i, "leaderboard", build_leaderboard_embed, "leaderboard")
 
@tree.command(name="setcompchannel", description="(Upline) Make THIS channel your live comp / payout view")
async def setcompchannel(i: discord.Interaction):
    await make_board(i, "comp", build_payout_embed, "payout view")
 
@tree.command(name="payout", description="(Upline) Your earnings this month, shown privately")
async def payout(i: discord.Interaction):
    if not upline_only(i): return await i.response.send_message("Upline only.", ephemeral=True)
    await i.response.send_message(embed=build_payout_embed(), ephemeral=True)
 
@tree.command(name="setcomp", description="(Upline) Set anyone's contract level %, including your own")
async def setcomp(i: discord.Interaction, member: discord.Member, percent: float):
    if not upline_only(i): return await i.response.send_message("Upline only.", ephemeral=True)
    db.execute("INSERT INTO comp VALUES(?, ?) ON CONFLICT(uid) DO UPDATE SET pct=excluded.pct", (member.id, percent))
    db.commit()
    await i.response.send_message(f"{member.display_name} is now at {percent:g}%.", ephemeral=True)
    await refresh_boards()
 
@tree.command(name="setdefault", description="(Upline) Level used for agents you haven't set")
async def setdefault(i: discord.Interaction, percent: float):
    if not upline_only(i): return await i.response.send_message("Upline only.", ephemeral=True)
    db.execute("UPDATE settings SET v=? WHERE k='default_pct'", (percent,)); db.commit()
    await i.response.send_message(f"Default agent level is now {percent:g}%.", ephemeral=True)
    await refresh_boards()
 
@tree.command(name="setadvance", description="(Upline) Months of advance (0-12)")
async def setadvance(i: discord.Interaction, months: float):
    if not upline_only(i): return await i.response.send_message("Upline only.", ephemeral=True)
    months = min(max(months, 0), 12)
    db.execute("UPDATE settings SET v=? WHERE k='advance'", (months,)); db.commit()
    await i.response.send_message(f"Advance is now {months:g} months.", ephemeral=True)
    await refresh_boards()
 
@tree.command(name="comp", description="(Upline) See everyone's current levels")
async def comp(i: discord.Interaction):
    if not upline_only(i): return await i.response.send_message("Upline only.", ephemeral=True)
    rows = db.execute("SELECT uid, pct FROM comp ORDER BY pct DESC").fetchall()
    lines = [f"<@{u}>: {p:g}%" + (" (you)" if u == UPLINE_ID else "") for u, p in rows]
    lines.append(f"\nDefault for anyone not listed: {setting('default_pct'):g}%")
    lines.append(f"Advance: {setting('advance'):g} months")
    await i.response.send_message("\n".join(lines), ephemeral=True)
 
 
@tree.command(name="setclientchannel", description="(Upline) Make THIS channel the live list of clients to pay out")
async def setclientchannel(i: discord.Interaction):
    await make_board(i, "clients", build_clients_embed, "client payout list")
 
@tree.command(name="clients", description="(Upline) Clients you still need to pay out, shown privately")
async def clients(i: discord.Interaction):
    if not upline_only(i): return await i.response.send_message("Upline only.", ephemeral=True)
    await i.response.send_message(embed=build_clients_embed(), ephemeral=True)
 
@tree.command(name="paid", description="(Upline) Mark a close as paid out to the agent")
async def paid(i: discord.Interaction, close_id: int):
    if not upline_only(i): return await i.response.send_message("Upline only.", ephemeral=True)
    n = db.execute("UPDATE closes SET paid=1 WHERE id=?", (close_id,)).rowcount; db.commit()
    await i.response.send_message(f"Close #{close_id} marked paid." if n else "No close with that number.", ephemeral=True)
    await refresh_boards()
 
@tree.command(name="unpaid", description="(Upline) Undo: mark a close as not paid yet")
async def unpaid(i: discord.Interaction, close_id: int):
    if not upline_only(i): return await i.response.send_message("Upline only.", ephemeral=True)
    n = db.execute("UPDATE closes SET paid=0 WHERE id=?", (close_id,)).rowcount; db.commit()
    await i.response.send_message(f"Close #{close_id} marked unpaid." if n else "No close with that number.", ephemeral=True)
    await refresh_boards()
 
@tree.command(name="paidagent", description="(Upline) Mark ALL of an agent's open closes as paid out")
async def paidagent(i: discord.Interaction, member: discord.Member):
    if not upline_only(i): return await i.response.send_message("Upline only.", ephemeral=True)
    n = db.execute("UPDATE closes SET paid=1 WHERE uid=? AND COALESCE(paid,0)=0", (member.id,)).rowcount; db.commit()
    await i.response.send_message(f"Marked {n} close{'s' if n != 1 else ''} paid for {member.display_name}.", ephemeral=True)
    await refresh_boards()
 
 
bot.run(TOKEN)
 