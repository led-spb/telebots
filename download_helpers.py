# -*- coding: utf-8 -*-
import re, os.path
import requests, cookielib
import json, bencode
import logging
import urlparse
import youtube_dl

def create_helper(url, proxy):
    p = urlparse.urlparse(url)
    baseurl = "%s://%s/" % (p[0],p.hostname)
    username = p.username
    password = p.password

    for cls in DownloadHelper.__subclasses__():
        if cls.check_url(baseurl):
            return cls(username, password, proxy)
    return None


class DownloadHelper(object):
  timeout = 10
  torrent_path = "."
  base_url = ""
  cookies = cookielib.CookieJar()

  def __init__(self, user, passwd, proxy):
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

  def download(self, url, target_path=None ):
     return None


class NnmClubDownloadHelper(DownloadHelper):
  base_url   = "https?://(nnm-club\.(name|me|to|tv|lib))|(nnmclub\.to)"

  def __init__(self, user, passwd, proxy ):
      DownloadHelper.__init__(self, user, passwd, proxy )
      self.session.proxies = {'http_proxy': proxy, 'htts_proxy': proxy }
      self.isAuth = None
      self.base_path = None
      pass

  def check_auth( self, req):
      #logging.debug(req.text)
      status = True if re.search( '<a\s+href="login.php\?logout', req.text, re.I+re.M )!=None else False
      logging.info("Noname-club auth status %s", "ok" if status else "fail" )
      return status
  
  def login(self):
      if self.isAuth:
         return
      url = '%s/forum/login.php' % self.base_path
      logging.info("Trying to login")

      req = self.session.get( url )
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
      self.isAuth = self.check_auth( req )
      if not self.isAuth:
         raise Exception("Could not login to tracker.")
      req.close()
      pass

  def download(self, url, target_path=None ):
      m = re.search('^https?://[^/]+', url)
      if m==None:
         raise Exception('Invalid URL: "%s"' % url )
      self.base_path = m.group(0)

      if self.isAuth==None:
         self.isAuth = self.check_auth( self.session.get('%s/forum/index.php' % self.base_path) )

      if not self.isAuth:
         self.login()

      m = re.search("viewtopic.php\\?(?:t|p)=(\\d+)", url)
      torrent = m.group(1)

      req = self.session.get( url )
      req.raise_for_status()

      #logging.debug( "==== begin page ====" )
      #logging.debug( req.text )
      #logging.debug( "==== end page ====" )

      torrent_id = ""
      match = re.search( "<a href=\"download.php\\?id=(\\d+)", req.text, re.I+re.M )
      if match:
         torrent_id = match.group(1)
      req.close()

      if torrent_id=="":
         raise Exception("Could not find download id")

      # download
      url = "%s/forum/download.php?id=%s" % (self.base_path, torrent_id )
      req = self.session.get( url )
      req.raise_for_status()

      filename = os.path.join( DownloadHelper.torrent_path if target_path ==None else target_path, "nnm_%s.torrent" % torrent)

      f = open( filename , "wb")
      f.write( req.content )
      f.close()
      req.close()
      return filename


class YoutubeDownloadHelper(DownloadHelper):
   base_url = 'https?://(www\.youtube\.com|youtu\.be)'

   def download(self, url, target_path=None ):
       ydl_opts = { 'outtmpl': os.path.join(target_path,'%(title)s.%(ext)s') }
       with youtube_dl.YoutubeDL(ydl_opts) as ydl:
          ydl.download([url])
       return target_path
