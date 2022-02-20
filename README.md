# litools
There are two tools, which can be run locally:
- Public chats — http://127.0.0.1:5000/chat
- Sandbag/Boost analysis — http://127.0.0.1:5000/boost

The program can be run from source (install the packages from requirements.txt) or release (currently only available for 64-bit Windows). The main settings are in the text file config.yml. 
Tested only on Windows in Python 3.7 with Firefox.

Once you have started the program, open in your browser one of the two pages listed above. If the page is already open, refresh it. To close the program, press Ctrl+C in the program window.

## Public chats
Watching chats of current official tournaments and broadcasts and creating reports of two kinds:
### Dubious words and phrases
Each report gets points based on an estimate of how bad they are supposedly. Points may be inaccurate because context is not taken into account. You can click on each report to see the history of chat messages, including previously deleted ones, on the left. Reports with high scores get a one-click timeout button named for the most likely reason. All messages have a two-click timeout button (Ban) and a Dismiss button. Reports are grouped by chat.
### Multi-line messages
Messages sent in a row or in a short period of time are grouped by user. The button for timeout in the header allows you to time out on the aggregate of all user messages. In this case, all the messages will be added to the log, unless they exceed 140 characters. To exclude some messages from the log, you can use the Exclude button(s) before you time out.
- This tool can be run without a token. In this case, everything will work except for the timeouts.
- For timeouts you need a web:mod enabled API token, which can be generated on Lichess in Preferences in the *API access tokens* section, where you can click *generate a personal access token*, activate the *Use moderator tools… web:mod* option, and push the *Submit* button. Put this token in the config.yml file, restart the program, and then refresh the web page.

## Sandbag/Boost
This tool does not require a token. However, for convenience, it is assumed that this tool (on the left) and Lichess (on the right) are open on the same page. Since Lichess does not allow embedding the content we want, by default you will see "lichess.org refused to connect" instead of the Lichess page. You can leave it as it is, but then I'm not sure that this tool will be useful. A hacky way to fix this in Firefox:
- Install and activate [this add-on]( https://addons.mozilla.org/en-US/firefox/addon/ignore-x-frame-options-header/?utm_source=addons.mozilla.org) in Firefox: 
- In Firefox, type `about:config` in the address bar and press Enter. A warning page may appear. Click *Accept the Risk and Continue* to go to the about:config page
- Search for the preference name `privacy.restrict3rdpartystorage.skip_list`
- If this preference doesn't exist, create it as a String
- Set its value to `http://127.0.0.1:5000,https://lichess.org`

## Feedback
Any suggestions for possible improvements and bug reports are welcome.
