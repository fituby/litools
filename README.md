# litools
There are several tools, e.g.:
- Public chats — http://127.0.0.1:5000/chat
- Sandbag/Boost analysis — http://127.0.0.1:5000/boost

## Deployment
1. Install the packages from requirements.txt.
2. Edit the following settings in config.yml:
    - `host: "127.0.0.1"`
    - `port: 5000`
    - `url: "https://some.website.org"`
    - everything else is best left by default

Tested only on Windows in Python 3.7 with Firefox.

## Public chats
Watching chats of current official tournaments/broadcasts and creating reports of two kinds:
1. Dubious words and phrases
2. Multiline messages
### Dubious words and phrases
Each report gets points based on an estimate of how bad they are supposedly. Points may be inaccurate because context is not taken into account. You can click on each report to see the history of chat messages, including previously deleted ones, on the left. Reports with high scores get a one-click timeout button named for the most likely reason. All messages have a two-click timeout button (Ban) and a Dismiss button. Reports are grouped by chat.
### Multiline messages
Messages sent in a row or in a short period of time are grouped by user. The button for timeout in the header allows you to time out on the aggregate of all user messages. In this case, all the messages will be added to the mod log, unless they exceed 140 characters. To exclude some messages from the log, you can use the Exclude button(s) before you time out.
### Chats, message grouping
After you click on a message, the program will open the full chat of the corresponding tournament/broadcast on the left. Then the notes and mod log of the author of the message, if any, will be displayed below the chat. You can leave only the messages of the user of interest if you toggle the button with the user's name in the chat header. If you click on any messages in this mode, the message will be added to the notes field. You will then be able to time out all selected messages at once (similar to the Multiline Messages section) and/or add them to the user's notes.

## Sandbag/Boost
The tool scans the last 100, 200, or 500 games of the player whose name is entered in the top field (or less if the player hasn't played that many games since the previous warning), and shows the results, highlighting important information if necessary. Many of the elements have tooltips. This should help to understand their purpose.

To add relevant information to the notes field, you can click the corresponding buttons in the tables. To warn or mark the player, click the appropriate button at the top right. If there is text in the notes field, your notes will be added at the same time as the selected action. If your action is successful, the corresponding information will be displayed below in the Mod Log and Notes sections.

### Embedding the Lichess window (OPTIONAL)
If you set `embed_lichess` to `true` in the config, the program will embed the Lichess window at the bottom, in which you can work with the report queue. Since Lichess does not allow embedding the content we want, by default you will see "lichess.org refused to connect" instead of the Lichess page. A hacky way to fix this in Firefox:
- Install and activate [this add-on]( https://addons.mozilla.org/en-US/firefox/addon/ignore-x-frame-options-header/?utm_source=addons.mozilla.org) in Firefox
- In the addon settings, replace the content of the *Websites can frame anything* field with `*://127.0.0.1:5000/*`
- In Firefox, type `about:config` in the address bar and press Enter. A warning page may appear. Click *Accept the Risk and Continue* to go to the about:config page
- Search for the preference name `privacy.restrict3rdpartystorage.skip_list`
- If this preference doesn't exist, create it as a String
- Set its value to `http://127.0.0.1:5000,https://lichess.org`

## Feedback
Any suggestions for possible improvements and bug reports are welcome.
