from discord.ext import commands
import numpy as np
import matplotlib.pyplot as plt
import discord
import json
import aiofiles
import time
import asyncio
from collections import defaultdict
import sys

# get token from text file
with open('token.txt') as f:
    TOKEN = f.read()


class MemeClient(commands.Bot):
    def __init__(self, command_prefix):
        super().__init__(command_prefix=command_prefix)
        self.default_key = {
            '😍': 2,
            '👍': 1,
            '👎': -1,
            '🤮': -2
        }
        self.default_prefix = 'j!'
        self.default_meme_timer = 24 # by default users have 24 hours to vote on a meme
        self.poll_rate = 30 # check for finished memes every 30 seconds
        self.owner_id = 169891281139531776 # owner's discord ID
        self.james_icon_url = 'https://cdn.discordapp.com/app-icons/232922698441949185/1d0f69cf7e1eced9f8d7b7a9aad86037.png'
        self.invite_url = 'https://discord.com/api/oauth2/authorize?client_id=513757460134232069&permissions=126016&scope=bot'
        self.welcome_speech = f"Hey, thanks for inviting me to your Discord server! To get set up, an admin will need to specify which channel is going to be your meme channel using `j!setchannel`. " \
                               "I'll watch that channel and add voting options to each meme posted (which have to be image attachments). After 24 hours, the votes are added up and the poster's " \
                               "total score will be updated. If the 🕒 emoji is there, then that means voting is still open! Type `j!help` to see what else I can do."
        self.competition = None

        # load the meme scores, the current memes, and the bot preferences
        with open('preferences.json') as preferences, open('new_memes.json') as memes, \
             open('current_memes.json') as current_memes:
            self.meme_scores   = json.load(memes)
            self.current_memes = json.load(current_memes)
            self.preferences   = json.load(preferences)
            # self.hashes        = json.load(hashes)

            # UPDATED MEMES.JSON FORMAT: meme_scores[str(message.guild.id)]["leaderboard" or "graph" or "submitted" or "records"]
            # ["leaderboard"][str(message.author.id)]["score" or "submitted"]
            # ["graph"][str(message.author.id)] is a list of tuples (individual meme score, meme # (for the server))
            # ["submitted"] is the # memes submitted to the server
            # ["records"]["best or words"] - each is a triple (message id, channel id, score)


    # sends the introductory message when first added to a server
    async def on_guild_join(self, guild):
        await guild.text_channels[0].send(self.welcome_speech)

    # output startup message and begin checking for finished meme timers
    async def on_ready(self):
        print(f'Logged in successfully as {self.user.name} (ID: {self.user.id})')
        print('------')
        await self.poll()

    # process commands, or check if the message is a meme to be voted on
    async def on_message(self, message):
        # ignore bot messages
        if message.author.bot:
            return

        if message.content.lower() == "unlucky":
            await message.channel.send("unlucky")
            return

        # process commands
        await self.process_commands(message)

        # if the meme channel has not been set, this will return None so the following
        # if statement will never run
        meme_channel = self.preferences["meme_channels"].get(str(message.guild.id))

        if message.channel.id == meme_channel:
            # check if the message has a meme attached
            if message.attachments:
                # get the image and hash it
                url = message.attachments[0].url
                # response = requests.get(url, stream=True)
                # img = Image.open(io.BytesIO(response.content))
                # meme_hash = imagehash.phash(img)

                # get the server's voting emojis and add them to the message
                key = self.get_key(message.guild)

                for emoji in key.keys():
                    await message.add_reaction(emoji)
                await message.add_reaction('🕒') # add clock emoji to show voting is open

                # add this to the list of memes currently being vote on
                try:
                    meme_timer = self.preferences["meme_timers"][str(message.guild.id)]
                except KeyError:
                    meme_timer = self.default_meme_timer

                # add this meme ID, its channel ID and its expiry time to the current memes dictionary
                self.current_memes[str(message.id)] = [message.channel.id, time.time() + 60*60*meme_timer]
                await self.save(self.current_memes, "current_memes.json")

    # check for finished memes
    async def poll(self):
        while True:
            # get the current time and prepare and empty list to fill with memes that have finished
            # this is necessary since popping dictionary elements during the below loop would cause a crash
            current_time = time.time()
            finished_memes = []

            # check which memes have finished and add them to the list
            for meme_id, (channel_id, finish_time) in self.current_memes.items():
                if finish_time < current_time:
                    finished_memes.append((channel_id, meme_id))

            # now loop through these memes and handle them
            for channel_id, meme_id in finished_memes:
                await self.handle_meme(channel_id, meme_id)
                self.current_memes.pop(meme_id)

            # update the JSON of current memes, in case of a restart
            await self.save(self.current_memes, "current_memes.json")
            await self.save(self.meme_scores, "new_memes.json")

            # wait then repeat
            await asyncio.sleep(self.poll_rate)

    # the procedure to follow for memes that have run out of voting time
    async def handle_meme(self, channel_id, meme_id):
        try:
            meme_channel = self.get_channel(channel_id)
            message = await meme_channel.fetch_message(meme_id)
        except:
            print(f"Either meme deleted or channel unavailable (message ID {meme_id}). Continuing...")
            return

        # remove the clock emoji to show voting time is over
        await message.remove_reaction(emoji='🕒', member=self.user)

        # calculate the meme's score
        key = self.get_key(message.guild)
        score = sum(key.get(react.emoji, 0) * (react.count-1) for react in message.reactions)

        # all keys must be strings because we're saving to JSON
        guild_id_str, author_id_str = str(message.guild.id), str(message.author.id)

        # check if the server exists in the meme scores dictionary
        if not self.meme_scores.get(guild_id_str, False):
            print(f"First meme on server {message.guild.name}! ({message.guild.id})")
            self.meme_scores[guild_id_str] = {"leaderboard": {}, "graph": {}, "submitted": 0, "records": {"best": (0, 0, -1), "worst": (0, 0, 100000)}}

        # check if the user has submitted a meme before
        if not self.meme_scores[guild_id_str]["leaderboard"].get(author_id_str, False):
            print(f"First meme on server {message.guild.name} from user {message.author.id}")
            self.meme_scores[guild_id_str]["leaderboard"][author_id_str] = {"score": 0, "submitted": 0}
            self.meme_scores[guild_id_str]["graph"][author_id_str] = []


        # check if the meme is the best or worst meme so far
        worst_score = self.meme_scores[guild_id_str]["records"]["worst"][2]
        best_score = self.meme_scores[guild_id_str]["records"]["best"][2]

        if score < worst_score:
            self.meme_scores[guild_id_str]["records"]["worst"] = (message.id, message.channel.id, score)

        if score > best_score:
            self.meme_scores[guild_id_str]["records"]["best"] = (message.id, message.channel.id, score)

        # calculate the user's new overall score
        user_updated_total = self.meme_scores[guild_id_str]["leaderboard"][author_id_str]["score"] + score

        # find what meme number this is for the server
        meme_num = self.meme_scores[guild_id_str]["submitted"] + 1

        # update the leaderboard info
        self.meme_scores[guild_id_str]["leaderboard"][author_id_str]["score"] = user_updated_total
        self.meme_scores[guild_id_str]["leaderboard"][author_id_str]["submitted"] += 1

        # update the graph-drawing info
        self.meme_scores[guild_id_str]["graph"][author_id_str].append((score, meme_num))

        # incremement the server's memes
        self.meme_scores[guild_id_str]["submitted"] += 1

        # print an update
        print(f"Meme from {message.author.name} in {message.guild.name} successfully processed with a score of {score}")

    # prevent users from voting on their own meme, or from voting multiple times
    async def on_reaction_add(self, user_reaction, user):
        if user == self.user:
            return

        message = user_reaction.message

        if message.channel.id == self.preferences["meme_channels"].get(str(message.guild.id)):
            if user == message.author:
                await message.remove_reaction(user_reaction, user)

            reactions = message.reactions

            for reaction in reactions:
                async for reacter in reaction.users():
                    if reacter == user and reaction.emoji != user_reaction.emoji:
                        await message.remove_reaction(user_reaction, user)

    # returns the data required to plot the distribution graph for a specific member
    def member_distribution_data(self, member):
        guild_id_str = str(member.guild.id)
        if bot.meme_scores.get(guild_id_str, None) is None:
            return {}

        member_data = bot.meme_scores[guild_id_str]["graph"].get(str(member.id), None)
        if member_data is None:
            return {}

        dist_dict = defaultdict(int)
        for meme_score, _ in member_data:
            dist_dict[meme_score] += 1

        return dist_dict

    # returns the data required to plot the distribution graph for the server
    def guild_distribution_data(self, guild):
        guild_id_str = str(guild.id)
        if bot.meme_scores.get(guild_id_str, None) is None:
            return {}

        server_data = bot.meme_scores[guild_id_str]["graph"]
        dist_dict = defaultdict(int)

        for user, user_memes in server_data.items():
            for meme_score, _ in user_memes:
                dist_dict[meme_score] += 1

        return dist_dict

    # helper function for saving a dictionary to JSON
    async def save(self, data, file_path):
        async with aiofiles.open(file_path, "w+") as f:
            await f.write(json.dumps(data, indent=4))

    # helper function to get a server's key
    def get_key(self, guild):
        key = self.preferences["keys"].get(str(guild.id), False)
        if not key:
            key = self.default_key

        return key


# allow dynamic command prefixes
def command_prefix(bot, message):
    try:
        # prefix = bot.prefixes[str(message.guild.id)]
        prefix = bot.preferences["prefixes"][str(message.guild.id)]
    except KeyError:
        prefix = bot.default_prefix

    return prefix


bot = MemeClient(command_prefix=command_prefix)#, help_command=CustomHelp())
bot.remove_command("help") # remove default help command, to be replaced with our own

### Bot commands ###

@bot.command(description="Show the distribution of meme scores, either for the whole server or for a specific user",
             help="Call this function on its own for stats on the whole server. Provide a single user for data on their memes specifically. Example usage: `<prefix>distribution <user mention>`")
async def distribution(ctx, member: discord.Member = None):
    if member is not None:
        data = bot.member_distribution_data(member)
        nick = member.nick
        if nick is None:
            nick = member.name
        title = f"Distribution of {nick}'s meme scores in {ctx.guild.name}"
    else:
        data = bot.guild_distribution_data(ctx.guild)
        title = f"Distribution of meme scores in {ctx.guild.name}"

    if not data:
        await ctx.send("I don't have enough data to produce a distribution graph. Either post some memes, or if you have, wait for the voting period to end.")
        return

    fig, ax = plt.subplots(figsize=(8, 6))

    meme_scores, score_freqs = data.keys(), data.values()

    plt.bar(meme_scores, score_freqs, color='white')
    plt.xticks(rotation=90)
    plt.ylabel('Frequency', color='white')
    plt.title(title, color='white')

    # Whiten
    ax.spines['bottom'].set_color('white')
    ax.spines['top'].set_color('white')
    ax.spines['right'].set_color('white')
    ax.spines['left'].set_color('white')
    ax.tick_params(axis='x', colors='white')
    ax.tick_params(axis='y', colors='white')
    ax.xaxis.label.set_color('white')
    ax.yaxis.label.set_color('white')

    plt.savefig('meme_dist.png', transparent=True)
    plt.clf()

    file = discord.File('meme_dist.png', filename='meme_dist.png')
    await ctx.channel.send(file=file)


@distribution.error
async def distributionerror(ctx, error): # fill in
    if isinstance(error, commands.errors.MemberNotFound):
        await ctx.send("That's not a valid member. Please use the desired user's mention as the only argument.")

@bot.command(aliases=['lb'],
            description="Display the meme leaderboards!",
            help="You don't need any help with that command!")
async def leaderboard(ctx):
    board = ""
    total_points = 0
    memes_submitted = 0
    try:
        leaderboard_data = bot.meme_scores[str(ctx.guild.id)]["leaderboard"]
    except KeyError:
        await ctx.send("I don't have enough data to produce a leaderboard. Either post some memes, or if you have, wait for the voting period to end.")
        return

    for pos, (user_id, info) in enumerate(sorted(leaderboard_data.items(), key=lambda user: user[1]["score"], reverse=True), 1):
        score, submitted = info["score"], info["submitted"]
        try:
            user = await ctx.guild.fetch_member(int(user_id))
        except discord.errors.NotFound:
            print(f"Leaderboard: user {user_id} no longer in server. Skipping.")
            continue

        nick = user.nick
        if not nick:
            nick = user.name

        board += f"{pos}. {nick}: {score} ({score / submitted :.1f} avg.)\n"
        total_points += score
        memes_submitted += submitted

    board += f"\nMemes submitted: {memes_submitted}. Average meme score: {total_points / memes_submitted : .2f}."

    # pull records data
    records = bot.meme_scores[str(ctx.guild.id)]["records"]
    best_message_id, best_channel_id, best_score = records["best"]
    worst_message_id, worst_channel_id, worst_score = records["worst"]

    best_channel = await bot.fetch_channel(best_channel_id)
    worst_channel = await bot.fetch_channel(worst_channel_id)

    best_meme = await best_channel.fetch_message(best_message_id)
    best_meme_url = best_meme.attachments[0].url

    worst_meme = await worst_channel.fetch_message(worst_message_id)
    worst_meme_url = worst_meme.attachments[0].url

    best_meme_author = best_meme.author
    worst_meme_author = worst_meme.author


    board += f"\nBest meme: [this one]({best_meme_url}), by {best_meme_author.mention} ({best_score} points)"
    board += f"\nWorst meme: [this one]({worst_meme_url}), by {worst_meme_author.mention} ({worst_score} points)"

    embed = discord.Embed(title=f"{ctx.guild.name} Leaderboards", description=board)
    embed.set_thumbnail(url=ctx.guild.icon_url)
    embed.set_author(name="james", icon_url=bot.james_icon_url)
    await ctx.send(embed=embed)

@bot.command(hidden=True)
async def calc_records(ctx):
    if ctx.author.id != bot.owner_id:
        return

    guild_id_str = str(ctx.guild.id)
    meme_channel_id = bot.preferences["meme_channels"][str(ctx.guild.id)]
    meme_channel = bot.get_channel(meme_channel_id)

    messages = await meme_channel.history(limit=None).flatten()
    num_memes = len(messages)

    bot.meme_scores[guild_id_str]["records"] = {"best": (0, 0, -1), "worst": (0, 0, 100000)}
    best_score, worst_score = -1, 1000000

    for meme_num, meme in enumerate(reversed(messages), 1):
        if bot.current_memes.get(str(meme.id)):
            break
        author_id_str = str(meme.author.id)
        key = bot.get_key(ctx.guild)
        meme_score = sum(key.get(react.emoji, 0) * (react.count-1) for react in meme.reactions)

        if meme_score < worst_score:
            worst_score = meme_score
            bot.meme_scores[guild_id_str]["records"]["worst"] = (meme.id, meme.channel.id, meme_score)

        if meme_score > best_score:
            best_score = meme_score
            bot.meme_scores[guild_id_str]["records"]["best"] = (meme.id, meme.channel.id, meme_score)

    await ctx.send("OK, records for this server set.")
    await bot.save(bot.meme_scores, "new_memes.json")

@bot.command(description="Plot a graph of users' points over time (displays best if all submitters have a different role colour in Discord)",
             help="You don't need any help with that command!")
async def graph(ctx):
    guild = ctx.guild
    guild_id_str = str(guild.id)
    try:
        graph_data = bot.meme_scores[guild_id_str]["graph"]
        total_memes = bot.meme_scores[guild_id_str]["submitted"]
    except KeyError:
        await ctx.send("There's no data to graph. Either post some memes, or if you have, wait for the voting period to end.")
        return

    # create a map ID string -> member object

    async def catch_fetch(user_id):
        try:
            return await guild.fetch_member(user_id)
        except discord.errors.NotFound:
            print(f"Graph: user {user_id} no longer in server. Skipping.")
            return None

    # members = {user_id: await guild.fetch_member(user_id) for user_id in graph_data.keys()}
    members = {user_id: await catch_fetch(user_id) for user_id in graph_data.keys()}
    members = {user_id: member for user_id, member in members.items() if member is not None}
    densities = {member: np.zeros(total_memes+1) for member in members.values()}
    cumulatives = densities.copy()

    for user_id, meme_data in graph_data.items():
        member = members.get(user_id)
        if member is None:
            continue

        for (meme_score, meme_num) in meme_data:
            densities[member][meme_num] = meme_score

        cumulatives[member] = np.cumsum(densities[member])

    fig, ax = plt.subplots(figsize=(12, 8))
    for member in sorted(cumulatives.keys(), key=lambda memb: cumulatives[memb][-1], reverse=True):
        nick = member.nick
        if not nick:
            nick = member.name

        plt.plot(range(total_memes+1), cumulatives[member], label=nick, color=tuple(c/255 for c in member.colour.to_rgb()))

    legend = plt.legend(framealpha=0)
    for text in legend.get_texts():
        text.set_color("white")

    plt.xlabel('Total Memes', color='white')
    plt.title(f'Meme Graph', color='white')
    plt.ylabel('User scores', color='white')

    # Whiten
    ax.spines['bottom'].set_color('white')
    ax.spines['top'].set_color('white')
    ax.spines['right'].set_color('white')
    ax.spines['left'].set_color('white')
    ax.tick_params(axis='x', colors='white')
    ax.tick_params(axis='y', colors='white')
    ax.xaxis.label.set_color('white')
    ax.yaxis.label.set_color('white')

    plt.savefig('graph.png', transparent=True)
    plt.clf()

    file = discord.File('graph.png', filename='graph.png')
    await ctx.channel.send('Tada!', file=file)

@bot.command(hidden=True)
async def convert(ctx):
    if ctx.author.id != bot.owner_id:
        return

    guild_id_str = str(ctx.guild.id)
    meme_channel_id = bot.preferences["meme_channels"][str(ctx.guild.id)]
    meme_channel = bot.get_channel(meme_channel_id)

    messages = await meme_channel.history(limit=None).flatten()
    num_memes = len(messages)

    bot.meme_scores[guild_id_str] = {"leaderboard": {}, "graph": {}, "submitted": num_memes}

    for meme_num, meme in enumerate(reversed(messages), 1):
        if bot.current_memes.get(str(meme.id)):
            break
        author_id_str = str(meme.author.id)
        key = bot.get_key(ctx.guild)
        meme_score = sum(key.get(react.emoji, 0) * (react.count-1) for react in meme.reactions)
        if not bot.meme_scores[guild_id_str]["leaderboard"].get(author_id_str, False):
            bot.meme_scores[guild_id_str]["leaderboard"][author_id_str] = {"score": meme_score, "submitted": 1}
            bot.meme_scores[guild_id_str]["graph"][author_id_str] = [(meme_score, meme_num)]
        else:
            bot.meme_scores[guild_id_str]["leaderboard"][author_id_str]["score"] += meme_score
            bot.meme_scores[guild_id_str]["leaderboard"][author_id_str]["submitted"] += 1
            bot.meme_scores[guild_id_str]["graph"][author_id_str].append((meme_score, meme_num))

    await ctx.send("OK, historical data converted.")
    await bot.save(bot.meme_scores, "new_memes.json")

@bot.command(description="Change james' prefix for this server",
             help="Provide a single prefix (no spaces allowed) to replace the existing one. Example usage: `<prefix>prefix !`")
async def prefix(ctx, *args):
    if has_general_permission(ctx.author):
        num_args = len(args)
        if num_args != 1:
            await ctx.send('Please try again with a single prefix (no spaces allowed)')
            return

        bot.preferences["prefixes"][str(ctx.guild.id)] = args[0]
        await ctx.send(f'Prefix updated to `{args[0]}` successfully.')
        await bot.save(bot.preferences, 'preferences.json')
    else:
        await ctx.send("Sorry, you don't have permission to do that.")

@bot.command(description="Give a user permission to change james' settings",
             help="Specify a single user to extend permissions to. Example usage: `<prefix>give_permission <user mention>`")
async def give_permission(ctx, target: discord.Member):
    if has_top_permission(ctx.author):
        try:
            if has_general_permission(target):
                await ctx.send('Hmm, seems like that person already had extended permissions!')
                return

            bot.preferences["admins"][str(ctx.guild.id)][str(target.id)] = 1
        except KeyError:
            bot.preferences["admins"][str(ctx.guild.id)] = {}
            bot.preferences["admins"][str(ctx.guild.id)][str(target.id)] = 1

        await ctx.send(f'OK, {target.mention} now has permission to use more of my commands.')
        await bot.save(bot.preferences, 'preferences.json')

    else:
        await ctx.send("Sorry, only administrators can modify my permissions.")

@bot.command(description="Take away a user's permission to change james' settings",
             help="Provide a single user to remove permissions for. Example usage: `<prefix>take_permission <user mention>`")
async def take_permission(ctx, target: discord.Member):
    if has_top_permission(ctx.author):
        if has_top_permission(target):
            await ctx.send("Sorry, you can't take that person's permissions away.")
            return
        try:
            bot.preferences["admins"][str(ctx.guild.id)].pop(str(target.id))
            await ctx.send(f'OK, {target.mention} has had his meme related permissions revoked.')
            await bot.save(bot.admins, 'admins.json')
        except KeyError:
            await ctx.send("Hmm, I don't think that person had extended permissions anyway!")

    else:
        await ctx.send("Sorry, only administrators can modify my permissions.")

@bot.command(hidden=True)
async def stop(ctx):
    if ctx.author.id == bot.owner_id:
        await ctx.send('Shutting down...')
        sys.exit()
    else:
        await ctx.send('Sorry, only my owner can tell me to do that 😋')

def has_general_permission(member):
    if has_top_permission(member):
        return True

    try:
        if str(member.id) in bot.preferences["admins"][str(member.guild.id)]:
            return True

    except KeyError:
        return False

    return False

def has_top_permission(member):
    return (member.guild_permissions.administrator or member.id == bot.owner_id)

@bot.command(description="Set the meme channel for this server",
             help="Provide a single channel for james to monitor for new memes. Example usage: `<prefix>setchannel <channel mention>`")
async def setchannel(ctx, channel : discord.TextChannel):
    if has_general_permission(ctx.author):
        bot.preferences["meme_channels"][str(ctx.guild.id)] = channel.id
        await ctx.send(f"OK, {channel.mention} is now your server's designated meme channel!")
        await bot.save(bot.preferences, 'preferences.json')
    else:
        await ctx.send("Sorry, you don't have permission to do that.")

@setchannel.error
async def setchannelerr(ctx, error):
    if isinstance(error, commands.errors.MissingRequiredArgument):
        await ctx.send(f"Please provide a single channel mention to set as the meme channel. Example usage: `{command_prefix(bot, ctx.message)}setchannel <channel mention>`")

@bot.command(description="Choose how long users will have to vote on memes",
             help="Provide a single value for the duration in hours users will be able to vote on a meme after it is posted. Example usage: `<prefix>settime 24`")
async def settime(ctx, arg : float):
    if has_general_permission(ctx.author):
        if arg < 48:
            bot.preferences["meme_timers"][str(ctx.guild.id)] = arg
            await bot.save(bot.preferences, "preferences.json")
            await ctx.send(f"OK, members will now have `{arg}` hour{'' if arg == 1 else 's'} to vote on memes.")
        else:
            await ctx.send("Sorry, my maximum setting is `48` hours. Try again with a smaller value.")
    else:
        await ctx.send("Sorry, you don't have permission to do that.")

@settime.error
async def settimeerr(ctx, error):
    if isinstance(error, commands.errors.MissingRequiredArgument):
        await ctx.send(f"Please provide a single value (in hours) to set as voting period length. Example usage: `{command_prefix(bot, ctx.message)}setchannel 12` will give users 12 hours to vote on memes in future.")

@bot.command(description="Add an emoji to the voting options on future memes",
             help="Provide a single emoji and an integer number of points for the emoji to represent in future. Example usage: `<prefix>add_emoji :laughing: 5`")
async def add_emoji(ctx, emoji, val: int):
    if not has_general_permission(ctx.author):
        await ctx.send("Sorry, you don't have permission to do that.")
        return

    await ctx.message.add_reaction(emoji)

    prev_key = bot.get_key(ctx.guild)

    if emoji in prev_key:
        await ctx.send("That emoji is already a voting option.")
        return

    key = {**prev_key, emoji:val}
    bot.preferences["keys"][str(ctx.guild.id)] = {k: v for k, v in sorted(key.items(), key=lambda item: item[1], reverse=True)}
    await bot.save(bot.preferences, "preferences.json")

    await ctx.send(f"OK! {emoji} will be worth {val} points on future memes!")

@add_emoji.error
async def add_emojierror(ctx, error):
    if isinstance(error, commands.errors.BadArgument):
        await ctx.send("The second argument must be an integer. Please try again.")
    elif isinstance(error, commands.errors.CommandInvokeError):
        await ctx.send("That's not a valid emoji. Please try again.")
    else:
        await ctx.send(f"Hmm, something went wrong. Please use the form `{command_prefix(bot, ctx.message)}add_emoji <emoji> <value>`")

@bot.command(description="Remove an emoji from the voting options on current and future memes",
             help="Provide a single emoji to remove from current/future meme voting options. Example usage: `<prefix>remove_emoji :thumbs_up:`")
async def remove_emoji(ctx, emoji):
    if not has_general_permission(ctx.author):
        await ctx.send("Sorry, you don't have permission to do that.")
        return

    await ctx.message.add_reaction(emoji)
    prev_key = bot.get_key(ctx.guild)
    if emoji not in prev_key.keys():
        await ctx.send("You can't remove something that's not there!")
    else:
        prev_key.pop(emoji)
        bot.preferences["keys"][str(ctx.guild.id)] = prev_key
        await bot.save(bot.preferences, "preferences.json")
        await ctx.send(f"OK, from now, votes with {emoji} will not be counted.")

@remove_emoji.error
async def remove_emojierror(ctx, error):
    if isinstance(error, commands.errors.CommandInvokeError):
        await ctx.send("That's not a valid emoji. Please try again.")
    else:
        await ctx.send(f"Hmm, something went wrong. Please use the form `{command_prefix(bot, ctx.message)}remove_emoji <emoji>`")

@bot.command(description="Display the current emoji options for meme voting",
             help="You don't need any help with that command!")
async def emojis(ctx):
    key = bot.get_key(ctx.guild)
    key_str = ""
    for emoji, val in key.items():
        key_str += f"{emoji} : {val} points\n"
    await ctx.send(key_str)


@bot.command(description="Shows this message",
             help="You don't need any help with that command!")
async def help(ctx, arg=None):
    commands = bot.commands
    prefix = command_prefix(bot, ctx.message)
    if not arg:
        help_emb = discord.Embed(title="james' Help Menu", colour=discord.Colour.dark_gold())

        for command in sorted(commands, key=lambda c: c.name):
            if not command.hidden:
                name = command.name
                help_emb.add_field(name=prefix+name, value=command.description, inline=False)

        help_emb.set_thumbnail(url=bot.james_icon_url)
        await ctx.send(embed=help_emb)

    else:
        for command in commands:
            if (arg == command.name or arg in command.aliases) and not command.hidden:
                await ctx.send(command.help.replace('<prefix>', prefix))
                return

        await ctx.send("That's not a valid command.")


@bot.command(hidden=True)
async def remove_reaction(ctx, message_id, reacter : discord.User, emoji):
    if ctx.author.id != bot.owner_id:
        return

    meme_channel_id = bot.preferences["meme_channels"].get(str(ctx.guild.id), None)
    if meme_channel_id is None:
        await ctx.send("I can't find a meme channel in your server :(")
        return

    meme = await bot.get_channel(meme_channel_id).fetch_message(message_id)
    await meme.remove_reaction(emoji=emoji, member=reacter)
    await ctx.send("Emoji removed!")
###

bot.run(TOKEN)
