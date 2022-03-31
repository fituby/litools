# litools
There are two tools, which can be run locally:
- Public chats — http://127.0.0.1:5000/chat
- Sandbag/Boost analysis — http://127.0.0.1:5000/boost

The program can be run from source (install the packages from requirements.txt) or release (currently only available for 64-bit Windows). The main settings are in the text file config.yml.
Tested only on Windows in Python 3.7 with Firefox.

Once you have started the program, leave it open in the background while you work on reports. Open in your browser one of the two pages listed above. If the page is already open, refresh it. To close the program, press Ctrl+C in the program window.

The program can be run without a token. In this case, everything will work except the actions that require the appropriate permissions (timeouts, warnings, reading/writing mod logs/notes, etc.). For mod actions, you need a web:mod enabled API token, which can be generated on Lichess in Preferences in the *API access tokens* section, where you can click *generate a personal access token*, activate the *Use moderator tools… web:mod* option, and push the *Submit* button. Put this token in the config.yml file, restart the program, and then refresh the web page.

## Public chats
Watching chats of current official tournaments/broadcasts and creating reports of two kinds:
1. Dubious words and phrases
2. Multiline messages
### Dubious words and phrases
Each report gets points based on an estimate of how bad they are supposedly. Points may be inaccurate because context is not taken into account. You can click on each report to see the history of chat messages, including previously deleted ones, on the left. Reports with high scores get a one-click timeout button named for the most likely reason. All messages have a two-click timeout button (Ban) and a Dismiss button. Reports are grouped by chat.
### Multiline messages
Messages sent in a row or in a short period of time are grouped by user. The button for timeout in the header allows you to time out on the aggregate of all user messages. In this case, all the messages will be added to the mod log, unless they exceed 140 characters. To exclude some messages from the log, you can use the Exclude button(s) before you time out.
### Chats, message grouping
After you click on a message, the program will open the full chat of the corresponding tournament/broadcast on the left. If `chat_notes` and `chat_mod_log` are set to *true* in the config, then the notes and mod log of the author of the message, if any, will be displayed below the chat. You can leave only the messages of the user of interest if you toggle the button with the user's name in the chat header. If you click on any messages in this mode, they will be added to the notes field. You will then be able to time out all selected messages at once (similar to the Multiline Messages section) and/or add them to the user's notes.

## Sandbag/Boost
The tool scans the last 100 games of the player whose name is entered in the top field (or less if the player hasn't played that many games since the previous warning), and shows the results, highlighting important information if necessary. Many of the elements have tooltips. This should help to understand their purpose.

To add relevant information to the notes field, you can click the corresponding buttons in the tables. To warn or mark the player, click the appropriate button at the top right. If there is text in the notes field, your notes will be added at the same time as the selected action. If your action is successful, the corresponding information will be displayed below in the Mod Log and Notes sections.

### Embedding the Lichess window (optional)
If you set `embed_lichess` to *true* in the config, the program will embed the Lichess window at the bottom, in which you can work with the report queue. Since Lichess does not allow embedding the content we want, by default you will see "lichess.org refused to connect" instead of the Lichess page. A hacky way to fix this in Firefox:
- Install and activate [this add-on]( https://addons.mozilla.org/en-US/firefox/addon/ignore-x-frame-options-header/?utm_source=addons.mozilla.org) in Firefox
- In the addon settings, replace the content of the *Websites can frame anything* field with `*://127.0.0.1:5000/*`
- In Firefox, type `about:config` in the address bar and press Enter. A warning page may appear. Click *Accept the Risk and Continue* to go to the about:config page
- Search for the preference name `privacy.restrict3rdpartystorage.skip_list`
- If this preference doesn't exist, create it as a String
- Set its value to `http://127.0.0.1:5000,https://lichess.org`

## Feedback
Any suggestions for possible improvements and bug reports are welcome.
