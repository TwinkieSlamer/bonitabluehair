XPReport kit for bonitabluehair.com
====================================

Two pieces:
  XPReport\                 a tiny WoW addon. It remembers only your level, your XP inside the
                            level, the XP the level needs, and when you level up.
  Start XP Uploader.bat     a small program that posts those numbers to bonitabluehair.com.
  XPUploader.ps1            (the uploader itself; the .bat just starts it)


1. Install the addon
--------------------
Copy the whole XPReport folder into your game's AddOns folder. It's the folder next to your
WTF folder, for example:

    C:\Program Files (x86)\World of Warcraft\_forever_\Interface\AddOns\XPReport\

(The middle folder name can differ. Use the one WoW: Forever actually launches from.)

Start the game. At character select, click AddOns and make sure XPReport is ticked.
If it says "Out of date", tick "Load out of date AddOns" at the top of that list.

In game, type /xpreport. You should see your level and XP printed in chat.


2. Start the uploader
---------------------
Double-click "Start XP Uploader.bat". A window opens.

The first time it asks for a GitHub key. Paste the key you were sent and press Enter.
It's stored encrypted for your Windows user only, so you won't be asked again.

Leave the window open while you play. Close it any time to stop uploading.


3. Push an update
-----------------
WoW only saves addon data when you log out or type /reload. So:

    /reload    sends your current XP right away (takes a few seconds in game)
    log out    also sends it

The uploader notices within about 10 seconds and the website shows it a few minutes later.


What it touches
---------------
The uploader reads one file, WTF\Account\<your account>\SavedVariables\XPReport.lua, and sends
your level and XP to github.com. It doesn't read anything else, change the game, or run in the
background after you close its window. To remove everything: delete the XPReport addon folder,
these files, and %APPDATA%\XPUploader.

If Windows blocks the .bat, right-click the zip you downloaded > Properties > tick "Unblock",
then extract it again.
