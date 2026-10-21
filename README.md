# Telegram Number Service Bot
Starter bot using a **reply keyboard** (not inline buttons), force-join channels/groups, SQLite, and temporary owners.

## Install
Python 3.10+ recommended.
1. Create a bot with @BotFather and copy its token.
2. Copy `.env.example` to `.env`; set `BOT_TOKEN` and your numeric `ADMIN_ID`.
3. Run `pip install -r requirements.txt`
4. Run `python bot.py`

## Force join
Make the bot an admin in each required channel so it can reliably check membership.
- `/addforcechannel @channel https://t.me/channel Channel Name`
- `/addforcegroup @group https://t.me/group Group Name`
- `/listforce`
- `/removeforce 1` (use the ID from `/listforce`)

Since you requested reply-keyboard buttons, tapping Join Channel/Join Group sends the relevant links in a message. Telegram reply-keyboard buttons cannot directly open URLs; direct URL buttons require inline keyboards.

## Temporary owners
Only the permanent owner set in `ADMIN_ID` can grant/remove temporary owners:
- `/addowner 123456789,30`
- `/removeowner 123456789`
- `/owners`
Temporary owners can manage force-join targets and view stats, but cannot grant owner access to others.

## Number provider
Get Number, Receive OTP, and Available Countries are menu placeholders until a legitimate provider API is selected and integrated. This project does not generate working numbers or retrieve OTPs without a provider. Never use it to access other people's accounts or messages.
