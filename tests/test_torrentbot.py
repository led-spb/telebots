from dummy_objects import DummyBot, DummyHTTPClient
import telebots
from telebots.torrentbot import TransmissionManager, UpdateChecker, NonameClub
from tornado import gen
from tornado.ioloop import IOLoop
import json
import pytest
import uuid
import random
from functools import partial


def async_wait(routine, timeout=15):
    @gen.coroutine
    def start(func):
        result = yield gen.maybe_future(func())
        raise gen.Return(result)

    IOLoop.current().run_sync(partial(start, routine), timeout)
    pass


@pytest.fixture
def manager():
    client = DummyHTTPClient(random_delay=1)
    manager = TransmissionManager(url="http://localhost:9091")
    manager.client = client
    yield manager


@pytest.fixture
def noname_helper():
    client = DummyHTTPClient(random_delay=1)
    helper = NonameClub(url="http://test_user:heres@nnm-club.to", proxy=None)
    helper.client = client
    yield helper


class TestNonameHelper(object):
    no_login_page = """
    <form action="login.php"/>
        <input type="hidden" name="redirect" value="" />
        <input type="hidden" name="code" value="5c60a7d378dfc316" />
    </form>
    """

    has_login_page = """
      <a href="login.php?logout=true&amp;sid=%s">Logout</a>
    """

    one_torrent_search = """
      <table class="forumline tablesorter other_class">
         <tr class="prow1">
            <td>0</td>
            <td>category_1</td>
            <td><a href="?t=123456789">name_1</a></td>
            <td>3</td>
            <td>4</td>
            <td>5</td>
            <td>6</td>
            <td>7</td>
            <td>8</td>
            <td>9</td>
         </tr>
         <tr class="prow2"></tr>
      </table>
    """

    def test_login(self, noname_helper):
        sid = str(uuid.uuid4())

        noname_helper.client.add(
            code=200,
            body=self.no_login_page,
            reason='OK',
            headers={}
        )
        noname_helper.client.add(
            code=200,
            body=self.has_login_page % sid,
            reason='OK',
            headers={}
        )
        IOLoop.current().run_sync(noname_helper.login)
        assert noname_helper.isAuth
        assert noname_helper.sid == sid

    def test_empty_search(self, noname_helper):
        noname_helper.client.add(
            code=200,
            body=self.no_login_page,
            reason='OK',
            headers={}
        )
        results = IOLoop.current().run_sync(partial(noname_helper.do_search, 'qwerty'))
        assert isinstance(results, list)
        assert len(results) == 0

    def test_normal_search(self, noname_helper):
        noname_helper.client.add(
            code=200,
            body=self.one_torrent_search,
            reason='OK',
            headers={}
        )
        results = IOLoop.current().run_sync(partial(noname_helper.do_search, 'qwerty'))
        assert isinstance(results, list)
        assert len(results) == 1
        assert results[0].link == noname_helper.base_url + 'forum/?t=123456789'


class TestManager(object):
    def test_torrent_list(self, manager):
        response = {
            "result": "success",
            "arguments": {
                "torrents": [
                ]
            }
        }
        manager.client.add(code=200, headers={}, body=json.dumps(response))
        torrents = IOLoop.current().run_sync(
            manager.get_torrents
        )
        assert len(torrents) == 0


@pytest.fixture(name='bot_handler')
def make_bot_handler(manager, noname_helper):
    bot = DummyBot()

    handler = UpdateChecker(
        manager=manager,
        trackers=[noname_helper]
    )
    bot.add_handler(handler)
    yield handler


class TestTorrentBot(object):
    def test_version(self, bot_handler):
        user_id = bot_handler.bot.admin
        chat_id = random.randint(1, 10000)

        assert bot_handler.bot.exec_command(
            message={"from": {"id": user_id}, "chat": {"id": chat_id}, "text": "/version"}
        )
        assert len(bot_handler.bot.messages) == 1
        message = bot_handler.bot.messages.pop()
        assert message['to'] == chat_id
        assert message['message'] == str(telebots.version)

    def test_unauth(self, bot_handler):
        user_id = bot_handler.bot.admin + 1000
        chat_id = random.randint(1, 10000)

        # search query
        assert not bot_handler.bot.exec_command(
            message={"from": {"id": user_id}, "chat": {"id": chat_id}, "text": str(uuid.uuid4())}
        )
        assert len(bot_handler.bot.messages) == 0
        # /version
        assert not bot_handler.bot.exec_command(
            message={"from": {"id": user_id}, "chat": {"id": chat_id}, "text": "/version"}
        )
        assert len(bot_handler.bot.messages) == 0
        # /status
        assert not bot_handler.bot.exec_command(
            message={"from": {"id": user_id}, "chat": {"id": chat_id}, "text": "/status"}
        )
        assert len(bot_handler.bot.messages) == 0
        # /update
        assert not bot_handler.bot.exec_command(
            message={"from": {"id": user_id}, "chat": {"id": chat_id}, "text": "/update"}
        )
        assert len(bot_handler.bot.messages) == 0

    def test_search(self, bot_handler):
        user_id = bot_handler.bot.admin
        chat_id = random.randint(1, 10000)

        executor = partial(
            bot_handler.bot.exec_command,
            message={
                "message_id": random.randint(0, 10000),
                "from": {"id": user_id},
                "chat": {"id": chat_id},
                "text": str(uuid.uuid4())
            }
        )
        async_wait(executor)

        assert len(bot_handler.bot.messages) == 1
        message = bot_handler.bot.messages.pop()
        assert message['to'] == chat_id
        assert message['message'] == "Search in progress..."
