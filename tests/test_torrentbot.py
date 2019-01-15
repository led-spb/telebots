from dummy_bot import DummyBot
import telebots
from telebots.torrentbot import TransmissionManager, UpdateChecker, NonameClub
from tornado.httpclient import HTTPError
from tornado.ioloop import IOLoop
from tornado import gen
import json
import pytest
import uuid
from functools import partial


class DummyResponse(object):
    def __init__(self, **kwargs):
        map(lambda item: setattr(self, item[0], item[1]), kwargs.items())

    def rethrow(self):
        if hasattr(self, 'code') and getattr(self, 'code') >= 399:
            raise HTTPError(code=getattr(self, 'code'), message="HTTPError")
        pass


class DummyHTTPClient(object):
    def __init__(self):
        self.responses = []

    @gen.coroutine
    def fetch(self, *args, **kwargs):
        raise gen.Return(self.responses.pop(0))
        pass

    def add(self, **kwargs):
        self.responses.append(DummyResponse(**kwargs))


@pytest.fixture
def dummy_client():
    client = DummyHTTPClient()
    yield client
    pass

@pytest.fixture
def manager(dummy_client):
    manager = TransmissionManager(url="http://localhost:9091")
    manager.client = dummy_client
    yield manager

@pytest.fixture
def noname_helper(dummy_client):
    helper = NonameClub(url="http://test_user:heres@nnm-club.to", proxy=None)
    helper.client = dummy_client
    yield helper


class TestNonameHelper:
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


class TestManager:
    def test_torrent_list(self, manager, dummy_client):
        response = {
            "result": "success",
            "arguments": {
                "torrents": [
                ]
            }
        }
        dummy_client.add(code=200, headers={}, body=json.dumps(response))
        torrents = IOLoop.current().run_sync(
            manager.get_torrents
        )
        assert len(torrents) == 0


class TestTorrentBot:

    @pytest.fixture
    def handler(self):
        bot = DummyBot()

        handler = UpdateChecker(
            manager=None,
            trackers=[]
        )
        bot.add_handler(handler)
        yield handler

    def test_version(self, handler):
        assert handler.bot.exec_command(
            message={
                "from": {"id": handler.bot.admin},
                "chat": {"id": 1234},
                "text": "/version"
            }
        )
        assert len(handler.bot.messages) == 1
        assert handler.bot.messages[0]['to'] == 1234
        assert handler.bot.messages[0]['message'] == str(telebots.version)

    def test_command_unauth(self, handler):
        assert not handler.bot.exec_command(
            message={
                "from": {"id": handler.bot.admin + 1000},
                "chat": {"id": -1},
                "text": "search query"
            }
        )
        assert len(handler.bot.messages) == 0
