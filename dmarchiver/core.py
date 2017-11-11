# -*- coding: utf-8 -*-

"""
    Direct Messages Archiver

    Usage:

    >>> from dmarchiver.core import Crawler
    >>> crawler = Crawler()
    >>> crawler.authenticate('username', 'password')
    >>> crawler.crawl('conversation_id')
"""

import collections
import datetime
from enum import Enum
import os
import pickle
import re
import shutil
from sys import platform
import time
import lxml.html
import requests

__all__ = ['Crawler']

# Expand short URL generated by Twitter


def expand_url(url):
    """Return the expanded URL behind a short link"""

    response = requests.get(url, allow_redirects=False)
    return response.headers['location']


class Conversation(object):
    """This class is a representation of a complete conversation"""

    conversation_id = None
    tweets = collections.OrderedDict()

    def __init__(self, conversation_id):
        self.tweets = collections.OrderedDict()
        self.conversation_id = conversation_id

    def print_conversation(self):
        """Print the conversation in the console"""

        items = list(self.tweets.items())
        items.reverse()

        for tweet in items:
            if type(tweet[1]).__name__ == 'DirectMessage':
                irc_formatted_date = datetime.datetime.fromtimestamp(
                    int(tweet[1].time_stamp)).strftime('%Y-%m-%d %H:%M:%S')
                print(
                    '[{0}] <{1}> '.format(
                        irc_formatted_date,
                        tweet[1].author),
                    end='')
                for element in tweet[1].elements:
                    print('{0} '.format(element), end='')
                print('\r')
            elif type(tweet[1]).__name__ == 'DMConversationEntry':
                print('[DMConversationEntry] {0}\r'.format(tweet[1]))

    def write_conversation(self, filename, max_id):
        """Write the content of the conversation to a file"""

        file_buffer = ''

        items = list(self.tweets.items())
        items.reverse()

        for tweet in items:
            if type(tweet[1]).__name__ == 'DirectMessage':
                irc_formatted_date = datetime.datetime.fromtimestamp(
                    int(tweet[1].time_stamp)).strftime('%Y-%m-%d %H:%M:%S')
                file_buffer += '[{0}] <{1}> '.format(
                    irc_formatted_date, tweet[1].author)
                for element in tweet[1].elements:
                    # Convert all '\n' of the buffer to os.linesep
                    # to handle tweets on multiple lines
                    file_buffer += '{0} '.format(
                        element).replace('\n', os.linesep)

                # Remove the last space of the line
                file_buffer = file_buffer[:-1]

                # Add the end of line character
                file_buffer += '{0}'.format(os.linesep)
            elif type(tweet[1]).__name__ == 'DMConversationEntry':
                file_buffer += '[DMConversationEntry] {0}{1}'.format(
                    tweet[1], os.linesep)

        # Write the latest tweet ID to allow incremental updates
        if len(items) > 0:
            file_buffer += '[LatestTweetID] {0}{1}'.format(
                tweet[1].tweet_id, os.linesep)
            if max_id != '0':
                with open(filename, 'rb+') as file:
                    lines = file.readlines()
                    # Remove last line and rewrite the file (poor
                    # performance...)
                    lines = lines[:-1]
                    file.seek(0)
                    file.write(b''.join(lines))
                    file.truncate()

            file_mode = "ab"
            if max_id == '0':
                file_mode = "wb"

            with open(filename, file_mode) as file:
                file.write(file_buffer.encode('UTF-8'))


class DMConversationEntry(object):
    """This class is a representation of a DMConversationEntry.

    It could be a when a new user join the group, when
    the group is renamed or the picture updated.
    """

    tweet_id = ''
    _text = ''

    def __init__(self, tweet_id, text):
        self.tweet_id = tweet_id
        self._text = text.strip()

    def __str__(self):
        return self._text


class DirectMessage(object):
    """This class is a representation of a Direct Message (a tweet)"""

    tweet_id = ''
    time_stamp = ''
    author = ''
    elements = []

    def __init__(self, tweet_id, time_stamp, author):
        self.tweet_id = tweet_id
        self.time_stamp = time_stamp
        self.author = author


class DirectMessageText(object):
    """ This class is a representation of simple text message.
    This is an "element" of the Direct Message.
    """

    _text = ''

    def __init__(self, text):
        self._text = text

    def __str__(self):
        return self._text


class DirectMessageTweet(object):
    """ This class is a representation of a quoted tweet.
    This is an "element" of the Direct Message.
    """

    _tweet_url = ''

    def __init__(self, tweet_url):
        self._tweet_url = tweet_url

    def __str__(self):
        return '[Tweet] {0}'.format(self._tweet_url)


class DirectMessageCard(object):
    """ This class is a representation of a card.
    A card is a preview of a posted link.
    This is an "element" of the Direct Message.
    """

    _card_url = ''
    _card_name = ''
    _expanded_url = ''

    def __init__(self, card_url, card_name):
        self._card_url = card_url
        self._card_name = card_name
        if 'https://t.co/' in card_url:
            self._expanded_url = expand_url(card_url)
        else:
            self._expanded_url = card_url

    def __str__(self):
        return '[Card-{1}] {0}'.format(self._expanded_url, self._card_name)


class MediaType(Enum):
    """ This class is a representation of the possible media types."""

    image = 1
    gif = 2
    video = 3
    sticker = 4
    unknown = 5


class DirectMessageMedia(object):
    """ This class is a representation of a embedded media.
    This is an "element" of the Direct Message.
    """

    _media_preview_url = ''
    _media_url = ''
    _media_alt = ''
    _media_type = ''

    def __init__(self, media_url, media_preview_url, media_alt, media_type):
        self._media_url = media_url
        self._media_preview_url = media_preview_url
        self._media_alt = media_alt
        self._media_type = media_type

    def __repr__(self):
        # Todo
        return "{0}('{1}','{2}','{3}')".format(
            self.__class__.__name__,
            self._media_url,
            self._media_preview_url,
            self._media_alt)

    def __str__(self):
        if self._media_preview_url != '':
            return '[Media-{0}] {1} [Media-preview] {2}'.format(
                self._media_type.name, self._media_url, self._media_preview_url)
        elif self._media_alt != '':
            return '[Media-{0}] [{1}] {2}'.format(
                self._media_type.name, self._media_alt, self._media_url)
        else:
            return '[Media-{0}] {1}'.format(
                self._media_type.name, self._media_url)


class Crawler(object):
    """ This class is a main component of the tool.
    It allows to create an authentication session,
    retrieve the conversation list and loop to gather all the tweets.
    """

    _twitter_base_url = 'https://twitter.com'
    _user_agent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/62.0.3202.89 Safari/537.36'
    if platform == 'darwin':
        _user_agent = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_13) AppleWebKit/603.1.13 (KHTML, like Gecko) Version/10.1 Safari/603.1.13'
    elif platform == 'linux' or platform == 'linux2':
        _user_agent = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/62.0.3184.0 Safari/537.36'

    _http_headers = {
        'User-Agent': _user_agent}
    _ajax_headers = {
        'User-Agent': _user_agent,
        'Accept': 'application/json, text/javascript, */*; q=0.01',
        'X-Requested-With': 'XMLHttpRequest'}

    _max_id_found = False
    _session = None

    def authenticate(self, username, password, save_session, raw_output):
        login_url = self._twitter_base_url + '/login'
        sessions_url = self._twitter_base_url + '/sessions'
        messages_url = self._twitter_base_url + '/messages'

        if save_session:
            try:
                with open('dmarchiver_session.dat', 'rb') as file:
                    self._session = pickle.load(file)
                    print('dmarchiver_session.dat found. Reusing a previous session, ignoring the provided credentials.')
                    # Test if the session is still valid
                    response = self._session.get(messages_url, headers=self._http_headers, allow_redirects=False)
                    if response.status_code == 200:
                        return
                    else:
                        self._session = None
                        print('Previous session is invalid. Creating a new session with provided credentials.')
            except FileNotFoundError:
                print('dmarchiver_session.dat not found. Creating a new session with provided credentials.')

        if save_session is False or self._session is None:
            self._session = requests.Session()

        if raw_output:
            raw_output_file = open(
                'authentication-{0}.txt'.format(username), 'wb')

        response = self._session.get(
            login_url,
            headers=self._http_headers)

        if raw_output:
            raw_output_file.write(response.content)
            raw_output_file.close()

        document = lxml.html.document_fromstring(response.text)
        authenticity_token = document.xpath(
            '//input[@name="authenticity_token"]/@value')[0]

        payload = {'session[username_or_email]': username,
                   'session[password]': password,
                   'authenticity_token': authenticity_token}

        response = self._session.post(
            sessions_url,
            headers=self._ajax_headers,
            params=payload)
        cookies = requests.utils.dict_from_cookiejar(self._session.cookies)
        if 'auth_token' in cookies:
            print('Authentication succeedeed.{0}'.format(os.linesep))
            
            if save_session:
                # Saving the session locally
                with open('dmarchiver_session.dat', "wb") as file:
                    pickle.dump(self._session, file)
        else:
            raise PermissionError(
                'Your username or password was invalid. Note: DMArchiver does not support multi-factor authentication or application passwords.')

    def get_threads(self, delay, raw_output):
        threads = []
        messages_url = self._twitter_base_url + '/messages'
        payload = {}
        first_request = False
        if raw_output:
            raw_output_file = open(
                'conversation-list.txt', 'wb')

        while True:
            response = self._session.get(
                messages_url,
                headers=self._ajax_headers,
                params=payload)

            if raw_output:
                raw_output_file.write(response.content)

            json = response.json()

            if 'errors' in json:
                print('An error occured during the parsing of the conversions.\n')
                if json['errors'][0]['code'] == 326:
                    print('''DMArchiver was identified as suspicious and your account as been temporarily locked by Twitter.
Don\'t worry, you can unlock your account by following the intructions on the Twitter website.
Maybe it\'s the first time you use it or maybe you have a lot of messages.
You can unlock your account and try again, and possibly use the -d option to slow down the tool.\n''')
                print('''Twitter error details below:
Code {0}: {1}\n'''.format(json['errors'][0]['code'], json['errors'][0]['message']))
                raise Exception('Stopping execution due to parsing error while retrieving the conversations')

            try:
                if first_request is False:
                    first_request = True
                    threads += json['inner']['trusted']['threads']

                    if json['inner']['trusted']['has_more'] is False:
                        break

                    payload = {'is_trusted': 'true', 'max_entry_id': json[
                        'inner']['trusted']['min_entry_id']}
                    messages_url = self._twitter_base_url + '/inbox/paginate?is_trusted=true&max_entry_id=' + \
                        json['inner']['trusted']['min_entry_id']
                else:
                    threads += json['trusted']['threads']

                    if json['trusted']['has_more'] is False:
                        break

                    payload = {'is_trusted': 'true',
                               'max_entry_id': json['trusted']['min_entry_id']}
                    messages_url = self._twitter_base_url + '/inbox/paginate?is_trusted=true&max_entry_id=' + \
                        json['trusted']['min_entry_id']
                
            except KeyError as ex:
                print(
                    'Unable to fully parse the list of the conversations. \
                     Maybe your account is locked or Twitter has updated the HTML code. \
                     Use -r to get the raw output and post an issue on GitHub. \
                     Exception: {0}'.format(str(ex)))
                break
            
            time.sleep(delay)
        if raw_output:
            raw_output_file.close()

        return threads

    def _get_latest_tweet_id(self, thread_id):
        filename = '{0}.txt'.format(thread_id)
        try:
            with open(filename, 'rb+') as file:
                lines = file.readlines()
                regex = r"^\[LatestTweetID\] ([0-9]+)"
                result = re.match(regex, lines[-1].decode('utf-8'))

                if result:
                    print('Latest tweet ID found in previous dump. Incremental update.')
                    return result.group(1)
                else:
                    print(
                        'Latest tweet ID not found in previous dump. Creating a new one with incremental support.')
        except IOError:
            print(
                "Previous conversation not found. Creating a new one with incremental support.")

        return '0'

    def _extract_dm_text_url(self, element, expanding_mode='only_expanded'):
        raw_url = ''
        if expanding_mode == 'only_expanded':
            raw_url = element.get('data-expanded-url')
        elif expanding_mode == 'only_short':
            raw_url = element.get('href')
        elif expanding_mode == 'short_and_expanded':
            raw_url = '{0} [{1}]'.format(element.get(
                'href'), element.get('data-expanded-url'))
        return raw_url

    def _extract_dm_text_hashtag(self, element):
        raw_hashtag = element.text_content()
        if element.tail is not None:
            raw_hashtag += element.tail
        return raw_hashtag

    def _extract_dm_text_atreply(self, element):
        raw_atreply = element.text_content()
        if element.tail is not None:
            raw_atreply += element.tail
        return raw_atreply

    # Todo: Implement parsing options
    def _extract_dm_text_emoji(self, element):
        raw_emoji = '{0}'.format(element.get('alt'))
        if element.tail is not None:
            raw_emoji += element.tail
        return raw_emoji

    def _parse_dm_text(self, element):
        dm_text = ''
        text_tweet = element.cssselect("p.tweet-text")[0]
        for text in text_tweet.iter('p', 'a', 'img'):
            if text.tag == 'a':
                # External link
                if 'twitter-timeline-link' in text.classes:
                    dm_text += self._extract_dm_text_url(text)
                # #hashtag
                elif 'twitter-hashtag' in text.classes:
                    dm_text += self._extract_dm_text_hashtag(text)
                # @identifier
                elif 'twitter-atreply' in text.classes:
                    dm_text += self._extract_dm_text_atreply(text)
                else:
                    # Unable to identify the link type, raw HTML output
                    dm_text += lxml.html.tostring(text).decode('UTF-8')
            # Emoji
            elif text.tag == 'img' and 'Emoji' in text.classes:
                dm_text += self._extract_dm_text_emoji(text)
            else:
                if text.text is not None:
                    dm_text += text.text
        return DirectMessageText(dm_text)

    def _parse_dm_media(
            self,
            element,
            tweet_id,
            time_stamp,
            download_images,
            download_gifs,
            download_videos):
        media_url = ''
        media_preview_url = ''
        media_alt = ''
        media_type = MediaType.unknown

        formatted_timestamp = datetime.datetime.fromtimestamp(
            int(time_stamp)).strftime('%Y%m%d-%H%M%S')

        img_url = element.find('.//img')
        gif_url = element.cssselect('div.PlayableMedia--gif')
        video_url = element.cssselect('div.PlayableMedia--video')

        if img_url is not None:
            media_url = img_url.get('data-full-img')
            media_alt = img_url.get('alt')
            media_filename_re = re.findall(r'/\d+/(.+)/(.+)$', media_url)
            media_sticker_filename_re = re.findall(
                '/stickers/stickers/(.+)$', media_url)

            if len(media_filename_re) > 0:
                media_type = MediaType.image
                media_filename = '{0}-{1}-{2}-{3}'.format(
                    formatted_timestamp, tweet_id, media_filename_re[0][0], media_filename_re[0][1])
            elif len(media_sticker_filename_re) > 0:
                # It is a sticker
                media_type = MediaType.sticker
                media_filename = 'sticker-' + media_sticker_filename_re[0]
            else:
                # Unknown media type
                print("Unknown media type")
            if media_filename is not None and download_images:
                response = self._session.get(media_url, stream=True)
                if response.status_code == 200:
                    os.makedirs(
                        '{0}/images'.format(self._conversation_id), exist_ok=True)
                    with open('{0}/images/{1}'.format(self._conversation_id, media_filename), 'wb') as file:
                        response.raw.decode_content = True
                        shutil.copyfileobj(response.raw, file)
        elif len(gif_url) > 0:
            media_type = MediaType.gif
            media_style = gif_url[0].find('div').get('style')
            media_preview_url = re.findall(r'url\(\'(.*?)\'\)', media_style)[0]
            media_url = media_preview_url.replace(
                'dm_gif_preview', 'dm_gif').replace('.jpg', '.mp4')
            media_filename_re = re.findall(r'dm_gif/(.+)/(.+)$', media_url)
            media_filename = '{0}-{1}-{2}'.format(formatted_timestamp, media_filename_re[0][
                0], media_filename_re[0][1])

            if download_gifs:
                response = self._session.get(media_url, stream=True)
                if response.status_code == 200:
                    os.makedirs(
                        '{0}/mp4-gifs'.format(self._conversation_id), exist_ok=True)
                    with open('{0}/mp4-gifs/{1}'.format(self._conversation_id, media_filename), 'wb') as file:
                        response.raw.decode_content = True
                        shutil.copyfileobj(response.raw, file)
        elif len(video_url) > 0:
            media_type = MediaType.video
            media_style = video_url[0].find('div').get('style')
            media_preview_url = re.findall(r'url\(\'(.*?)\'\)', media_style)[0]
            media_url = 'https://twitter.com/i/videos/dm/' + tweet_id
            video_url = 'https://mobile.twitter.com/messages/media/' + tweet_id
            media_filename = '{0}-{1}.mp4'.format(
                formatted_timestamp, tweet_id)

            if download_videos:
                response = self._session.get(video_url, stream=True)
                if response.status_code == 200:
                    os.makedirs(
                        '{0}/mp4-videos'.format(self._conversation_id), exist_ok=True)
                    with open('{0}/mp4-videos/{1}'.format(self._conversation_id, media_filename), 'wb') as file:
                        response.raw.decode_content = True
                        shutil.copyfileobj(response.raw, file)

        else:
            print('Unknown media')

        return DirectMessageMedia(media_url, media_preview_url, media_alt, media_type)

    def _parse_dm_tweet(self, element):
        tweet_url = ''
        tweet_url = element.cssselect('a.QuoteTweet-link')[0]
        tweet_url = '{0}{1}'.format(
            self._twitter_base_url, tweet_url.get('href'))
        return DirectMessageTweet(tweet_url)

    def _parse_dm_card(self, element):
        card_url = ''
        card = element.cssselect(
            'div[class^=" card-type-"], div[class*=" card-type-"]')[0]
        return DirectMessageCard(
            card.get('data-card-url'),
            card.get('data-card-name'))

    def _process_tweets(self, tweets, download_images, download_gifs, download_videos, max_id):
        conversation_set = collections.OrderedDict()
        ordered_tweets = sorted(tweets, reverse=True)

        # DirectMessage-message
        # -- DirectMessage-text
        # -- DirectMessage-media
        # -- DirectMessage-tweet
        # -- DirectMessage-card

        for tweet_id in ordered_tweets:
            dm_author = ''
            message = ''
            dm_element_text = ''
            value = tweets[tweet_id]

            # If we reached the previous max tweet id,
            # we stop the execution
            if tweet_id == max_id:
                self._max_id_found = True
                print('Previous tweet limit found.')
                break

            try:
                document = lxml.html.fragment_fromstring(value)

                dm_container = document.cssselect(
                    'div.DirectMessage-container')

                # Generic messages such as "X has join the group" or "The group has
                # been renamed"
                dm_conversation_entry = document.cssselect(
                    'div.DMConversationEntry')

                if len(dm_container) > 0:
                    dm_avatar = dm_container[0].cssselect(
                        'img.DMAvatar-image')[0]
                    dm_author = dm_avatar.get('alt')

                    # print(dm_author)

                    dm_footer = document.cssselect('div.DirectMessage-footer')
                    time_stamp = dm_footer[0].cssselect('span._timestamp')[
                        0].get('data-time')

                    # DirectMessage-text, div.DirectMessage-media,
                    # div.DirectMessage-tweet_id, div.DirectMessage-card...
                    # First select is for non-text messages, second one is for
                    # text messages, last one is a special case for stickers
                    dm_elements = document.cssselect(
                        'div.DirectMessage-message > div.DirectMessage-attachmentContainer > div[class^="DirectMessage-"], div.DirectMessage-message > div.DirectMessage-contentContainer > div[class^="DirectMessage-"], div.DirectMessage-message > div.DirectMessage-media')

                    message = DirectMessage(tweet_id, time_stamp, dm_author)

                    # Required array cleanup
                    message.elements = []
                    for dm_element in dm_elements:
                        dm_element_type = dm_element.get('class')
                        if 'DirectMessage-text' in dm_element_type:
                            element_object = self._parse_dm_text(dm_element)
                            message.elements.append(element_object)
                        elif 'DirectMessage-media' in dm_element_type:
                            element_object = self._parse_dm_media(
                                dm_element, tweet_id, time_stamp, download_images, download_gifs, download_videos)
                            message.elements.append(element_object)
                        elif 'DirectMessage-tweet' in dm_element_type:
                            element_object = self._parse_dm_tweet(dm_element)
                            message.elements.append(element_object)
                        elif 'DirectMessage-card' in dm_element_type:
                            element_object = self._parse_dm_card(dm_element)
                            message.elements.append(element_object)
                        else:
                            print('Unknown element type')

                elif len(dm_conversation_entry) > 0:
                    dm_element_text = dm_conversation_entry[0].text.strip()
                    message = DMConversationEntry(tweet_id, dm_element_text)
            except KeyboardInterrupt:
                print(
                    'Script execution interruption requested. Writing the conversation.')
                self._max_id_found = True
                break
            except:
                print(
                    'Unexpected error for tweet \'{0}\', raw HTML will be used for the tweet.'.format(tweet_id))
                message = DMConversationEntry(
                    tweet_id, '[ParseError] Parsing of tweet \'{0}\' failed. Raw HTML: {1}'.format(
                        tweet_id, value))

            if message is not None:
                conversation_set[tweet_id] = message

        return conversation_set

    def crawl(
            self,
            conversation_id,
            delay=0,
            download_images=False,
            download_gifs=False,
            download_videos=False,
            raw_output=False):

        raw_output_file = None

        if raw_output:
            raw_output_file = open(
                '{0}-raw.txt'.format(conversation_id), 'wb')

        print('{0}Starting crawl of \'{1}\''.format(
            os.linesep, conversation_id))

        # Attempt to find the latest tweet id of a previous crawl session
        max_id = self._get_latest_tweet_id(conversation_id)

        self._conversation_id = conversation_id
        conversation = Conversation(conversation_id)
        conversation_url = self._twitter_base_url + '/messages/with/conversation'
        payload = {'id': conversation_id}
        processed_tweet_counter = 0

        try:
            while True and self._max_id_found is False:
                response = self._session.get(
                    conversation_url,
                    headers=self._ajax_headers,
                    params=payload)

                json = response.json()

                if 'errors' in json:
                    print('An error occured during the parsing of the tweets.\n')
                    if json['errors'][0]['code'] == 326:
                        print('''DMArchiver was identified as suspicious and your account as been temporarily locked by Twitter.
Don\'t worry, you can unlock your account by following the intructions on the Twitter website.
Maybe it\'s the first time you use it or maybe you have a lot of messages.
You can unlock your account and try again, and possibly use the -d option to slow down the tool.\n''')
                    print('''Twitter error details below:
Code {0}: {1}\n'''.format(json['errors'][0]['code'], json['errors'][0]['message']))
                    raise Exception('Stopping execution due to parsing error while retrieving the tweets.')

                if 'max_entry_id' not in json:
                    print('Begin of thread reached')
                    break

                payload = {'id': conversation_id,
                           'max_entry_id': json['min_entry_id']}

                tweets = json['items']

                if raw_output:
                    ordered_tweets = sorted(tweets, reverse=True)
                    for tweet_id in ordered_tweets:
                        raw_output_file.write(tweets[tweet_id].encode('UTF-8'))

                # Get tweets for the current request
                conversation_set = self._process_tweets(
                    tweets, download_images, download_gifs, download_videos, max_id)

                # Append to the whole conversation
                for tweet_id in conversation_set:
                    processed_tweet_counter += 1
                    conversation.tweets[tweet_id] = conversation_set[tweet_id]
                    print('Processed tweets: {0}\r'.format(
                        processed_tweet_counter), end='')
            
                time.sleep(delay)
        except KeyboardInterrupt:
            print(
                'Script execution interruption requested. Writing this conversation.')

        if raw_output:
            raw_output_file.close()

        print('Total processed tweets: {0}'.format(processed_tweet_counter))

        # print('Printing conversation')
        # conversation.print_conversation()

        print('Writing conversation to {0}.txt'.format(
            os.path.join(os.getcwd(), conversation_id)))
        conversation.write_conversation(
            '{0}.txt'.format(conversation_id), max_id)

        self._max_id_found = False
