# -*- coding: utf-8 -*-
import re, os.path
import requests
import logging
import urllib
import youtube_dl
import lxml.cssselect
import lxml.html
import cookielib
#import dateparser
import datetime


class DownloadHelper(object):
    timeout   = 10
    base_url  = ""
    cookies   = cookielib.CookieJar()
    proxy     = None

    def __init__(self, user=None, passwd=None):
        self.user     = user
        self.passwd   = passwd

        self.session = requests.Session()
        self.session.cookies = DownloadHelper.cookies
        self.session.headers = {
              'User-Agent': 'Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/29.0.1547.66 Safari/537.36',
              'Accept-Charset': 'utf-8'
        }

    @classmethod
    def check_url(cls, url):
        return re.search("^%s" % cls.base_url, url) != None

    def enable_proxy(self):
        if self.proxy!=None:
           self.session.proxies = { 'http': self.proxy, 'https': self.proxy }

    def disable_proxy(self):
        self.session.proxies = {}

    def download(self, url, target_path=None ):
        req = self.session.get( url )
        url_hash = filter(None,url.split("/"))[-1]
        filename = os.path.join( "." if target_path == None else target_path, "%s_%s.torrent" % (self.name, url_hash) )
        f = open( filename , "wb")
        f.write( req.content )
        f.close()
        req.close()
        return filename

    def do_search(self, query):
        return []


class ResultItem:
    __attributes__ = ['id', 'title', 'category', 'link', 'added', 'size']

    def __init__(self, **kwargs ):
        self.__data__ = kwargs
        pass

    def __getattr__(self, item):
        if item in self.__class__.__attributes__:
            return self.__data__[item] if item in self.__data__ else None
        return None


class RutorHelper(DownloadHelper):
  base_url   = "http://new-rutor.org"
  name       = "rutor"

  def do_search(self, query):
      if query.strip()=='':
         return []
      url = u"%s/search/%s/" % (self.base_url, query )
      logging.debug("url: %s", url)
      req = self.session.get(url)
      req.raise_for_status()
      req.encoding = 'utf-8'

      tree = lxml.html.fromstring( req.text )
      req.close()

      sel = lxml.cssselect.CSSSelector( u"tr.gai,tr.tum" )
      results = []
      for item in sel(tree):
         results.append( self.parse_result(item) )
      return results

  def parse_result(self, element):
      cells = element.cssselect('td')

      href     = cells[1].cssselect('a')[0].attrib['href']
      link     = self.base_url + href + '/'

      m = re.search('(\d+)$', href)
      item_id = m.group(1)

      title    = cells[1].cssselect('a')[1].text_content().strip()
      category = 'rutor'
      size     = cells[3].text_content().strip()

      date_str = cells[0].text_content().strip()
      added    = dateparser.parse( date_str, languages=['ru','en'] )# - datetime.datetime(1970, 1, 1) ).total_seconds() )
      if added != None:
         added = (added - datetime.datetime(1970, 1, 1) ).total_seconds()
      else:
         added = 0
      return ResultItem(id="_rutor_"+item_id, title=title, category=category, link=link, added=added, size=size)


class NnmClubHelper(DownloadHelper):
  base_url   = "https?://(nnm-club\.(name|me|to|tv|lib))|(nnmclub\.to)"
  name       = "nnmclub"

  def __init__(self, user, passwd ):
      DownloadHelper.__init__(self, user, passwd )
      self.isAuth = None
      self.base_path = None
      pass

  def _check_auth( self, req):
      status = True if re.search( '<a\s+href="login.php\?logout', req.text, re.I+re.M )!=None else False
      logging.info("Noname-club auth status %s", "ok" if status else "fail" )
      return status
  
  def login(self, req=None):
      if self.isAuth:
         return
      url = '%s/forum/login.php' % self.base_path
      logging.info("Trying to login at %s" % url )

      if req==None:
         req = self.session.get( url, stream=False )

      m = re.search('<form.*?action="login.php".*?>(.*?)</form>', req.text, re.I+re.M+re.U+re.S)
      form = m.group(1)
      req.close()

      login_data = { 'login':  u'Вход'.encode('windows-1251'), 
                     'username': self.user, 'password': 
                     self.passwd, 'autologin':'on' 
      }

      for m in re.finditer(r'<input\s+type="hidden"\s+name="(.*?)"\s+value="(.*?)"', form, re.I+re.M+re.S ):
          login_data[ m.group(1) ] = m.group(2)

      req = self.session.post( url, data = login_data )
      req.raise_for_status()

      self.isAuth = self._check_auth( req )
      if not self.isAuth:
         raise Exception("Could not login to tracker.")
      req.close()
      pass

  def do_search(self, query):
      if query.strip()=='':
         return []
      self.enable_proxy()
      url = "http://nnm-club.me/forum/tracker.php"
      req = self.session.post(url, data = {
            'f': u'-1',
            'nm': query.encode('windows-1251'), 
            'submit_search': (u'Поиск').encode('windows-1251'),
      })
      req.raise_for_status()
      self.base_url = os.path.dirname( req.url )

      tree = lxml.html.fromstring( req.text )
      sel = lxml.cssselect.CSSSelector( u"table.forumline.tablesorter tr.prow1,tr.prow2" )
      results = []
      for item in sel(tree):
         results.append( self.parse_result(item) )
      return results

  def parse_result(self, element):
      cells = element.cssselect('td')

      href     = cells[2].cssselect('a')[0].attrib['href']
      m = re.search('\?t=(.*)$', href)
      item_id = m.group(1)

      title    = cells[2].text_content().strip()
      category = cells[1].text_content().strip()
      size     = int(cells[5].cssselect('u')[0].text_content().strip())
      added    = int(cells[9].cssselect('u')[0].text_content().strip())

      return ResultItem(id="_nnm_"+item_id, title=title, category=category, link=os.path.join(self.base_url,href), added=added, size=size)


  def download(self, url, target_path=None ):
      self.enable_proxy()
      logging.info( "Start downloading %s" % url )
      m = re.search('^https?://[^/]+', url)
      if m==None:
         raise Exception('Invalid URL: "%s"' % url )
      self.base_path = m.group(0)
      req = None

      if self.isAuth==None:
         login_url = '%s/forum/index.php' % self.base_path
         logging.info( "Check login status at %s" % login_url )
         logging.info( self.session.proxies )

         req = self.session.get( login_url, stream=False)
         self.isAuth = self._check_auth( req )

      if not self.isAuth:
         self.login( req )

      m = re.search("viewtopic.php\\?(?:t|p)=(\\d+)", url)
      torrent = m.group(1)

      req = self.session.get( url )
      req.raise_for_status()

      torrent_id = ""
      match = re.search( "<a href=\"download.php\\?id=(\\d+)", req.text, re.I+re.M )
      if match:
         torrent_id = match.group(1)
      req.close()

      if torrent_id=="":
         raise Exception("Could not find download id")

      # download
      url = u"%s/forum/download.php?id=%s" % (self.base_path, torrent_id )
      req = self.session.get( url )
      req.raise_for_status()

      filename = os.path.join( "." if target_path == None else target_path, "nnm_%s.torrent" % torrent)

      f = open( filename , "wb")
      f.write( req.content )
      f.close()
      req.close()
      return filename




class YoutubeHelper(DownloadHelper):
   base_url = 'https?://(www\.youtube\.com|youtu\.be)'

   def download(self, url, target_path=None ):
       ydl_opts = { 'outtmpl': unicode(os.path.join(target_path,'%(title)s.%(ext)s')) }
       with youtube_dl.YoutubeDL(ydl_opts) as ydl:
          res = ydl.extract_info( url )
          filename = ydl.prepare_filename( res )
          return filename
      
