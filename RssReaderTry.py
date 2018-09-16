# !/usr/bin/env python
# coding: utf-8

'''RssReaderTry

Rssリーダを作ってみる。
sublimeでビルドするとエラーになるけど、terminalからだと成功するからこれでいいや。
'''

import feedparser, datetime, json, webbrowser, sqlite3, os

RSS_URL = "http://qiita.com/mpyw/feed.atom"

class MyRssReader:
    def main(self):
        # 1. RSS_URLとrssUrlをキーにDBのcreateTimeを取得する(そもそもないならcreateCacheへ)
        connection = sqlite3.connect("my_rss.sqlite3")
        cursor     = connection.cursor()
        query      = "SELECT createTime FROM rss_data WHERE rssUrl=?;"
        cursor.execute(query, (RSS_URL,))
        trash      = cursor.fetchall()
        cursor.close()
        connection.close()
        if not trash:
            # ないので新規登録する
            cacheDic = self.createCache()
        else:
            # 2. createTimeが6時間(21600s)以上前だったらupdateCacheへ
            createTime = self.assoc(trash, ["createTime"])[0]["createTime"]
            timeNow = datetime.datetime.today()
            timeBefore = datetime.datetime(
                int(createTime[0:4]),
                int(createTime[4:6]),
                int(createTime[6:8]),
                int(createTime[8:10]),
                int(createTime[10:12]),
                )
            delta = round((timeNow - timeBefore).total_seconds())
            if delta >= 21600:
                cacheDic = self.updateCache()
            else:
                # DBのjsonDataをそのままcacheDicにする
                connection = sqlite3.connect("my_rss.sqlite3")
                cursor     = connection.cursor()
                query      = "SELECT jsonData FROM rss_data WHERE rssUrl=?"
                cursor.execute(query, (RSS_URL,))
                trash      = cursor.fetchall()
                cursor.close()
                connection.close()
                jsonData = self.assoc(trash, ["jsonData"])[0]["jsonData"]
                cacheDic = json.loads(jsonData)

        # 4. cacheDicからhtmlを作って、webbrowserでオープン。以上
        webbrowser.open(self.createHtml(cacheDic))

    def assoc(self, trash, columns):
        rows = []
        for i in range(len(trash)):
            rows.append({})
            for j in range(len(trash[i])):
                rows[i][columns[j]] = trash[i][j]
        return rows

    # ==============================
    # feedparser使ってcacheDic作る
    # ==============================
    def createCacheDic(self):
        # 1. feedparserでRSS_URLを読む
        original = feedparser.parse(RSS_URL)
        cacheDic = {}

        # cacheDicにデータを追加していく
        cacheDic["siteTitle"]  = original.feed.title
        cacheDic["siteUrl"]    = original.feed.link
        cacheDic["rssUrl"]     = RSS_URL
        timeNow = datetime.datetime.today()
        cacheDic["createTime"] = (str(timeNow.year) +
            str("{0:02d}".format(timeNow.month)) +
            str("{0:02d}".format(timeNow.day)) +
            str("{0:02d}".format(timeNow.hour)) +
            str("{0:02d}".format(timeNow.minute))
            )
        cacheDic["articleNum"] = len(original.entries)
        for i in range(len(original.entries)):
            entry = original.entries[i]
            date  = entry.updated_parsed
            month = "{0:02d}".format(date.tm_mon)
            day   = "{0:02d}".format(date.tm_mday)
            cacheDic["article" + str(i)] = {
                "title":entry.title,
                "url"  :entry.link,
                "date" :"%s/%s/%s" % (date.tm_year, month, day)
                }

        return cacheDic

    # ==============================
    # DBに追加
    # ==============================
    def createCache(self):
        cacheDic = self.createCacheDic()

        # 2. DBにcacheDicを登録
        connection = sqlite3.connect("my_rss.sqlite3")
        cursor     = connection.cursor()
        query      = ("INSERT INTO rss_data " +
            "(siteTitle, siteUrl, createTime, jsonData, rssUrl) VALUES (?,?,?,?,?)")
        values = (cacheDic["siteTitle"], cacheDic["siteUrl"], cacheDic["createTime"], json.dumps(cacheDic), cacheDic["rssUrl"])
        cursor.execute(query, values)
        connection.commit()
        cursor.close()
        connection.close()

        # 3. cacheDicを返す
        return cacheDic

    # ==============================
    # DBを更新
    # ==============================
    def updateCache(self):
        cacheDic = self.createCacheDic()

        # 2. DBにcacheDicを更新
        connection = sqlite3.connect("my_rss.sqlite3")
        cursor     = connection.cursor()
        query      = ("UPDATE rss_data SET " +
            "siteTitle=?," +
            "siteUrl=?," +
            "createTime=?," +
            "jsonData=? "  +
            "WHERE rssUrl=?;"
            )
        values = (cacheDic["siteTitle"], cacheDic["siteUrl"], cacheDic["createTime"], json.dumps(cacheDic), cacheDic["rssUrl"])
        cursor.execute(query, values)
        connection.commit()
        cursor.close()
        connection.close()

        # 3. cacheDicを返す
        return cacheDic

    # ==============================
    # cacheDicからhtmlを作ってhtmlファイルとして保存
    # ==============================
    def createHtml(self, cacheDic):
        tmp = cacheDic["createTime"]
        createTime = "%s/%s/%s %s:%s" % (tmp[0:4], tmp[4:6], tmp[6:8], tmp[8:10], tmp[10:12])
        htmlData = (
            "<html><head><meta http-equiv='Content-Type' content='text/html; charset=utf-8'>" +
            "<title>自作PythonRSS</title></head>" +
            "<body><div style='margin:20px;background-color:khaki;padding:10px;'>" +
            "<h3>Articles of site: <a href='%s'>%s</a></h3>" % (cacheDic["siteUrl"], cacheDic["siteTitle"]) +
            "<ul>"
            )
        for i in range(cacheDic["articleNum"]):
            arti = cacheDic["article" + str(i)]
            htmlData += "<li>%s -- <a href='%s'>%s</a></li>" % (arti["date"], arti["url"], arti["title"])
        htmlData += "</ul><h4>This RSS was made at %s</h4></div></body></html>" % createTime

        fileName = "myrss - "+cacheDic["siteTitle"]+".html"
        with open("html/"+fileName, encoding="utf-8", mode="w") as fopen:
            fopen.write(htmlData)

        return os.path.realpath("html/"+fileName)


if __name__ == "__main__":
    myrss = MyRssReader()
    myrss.main()
