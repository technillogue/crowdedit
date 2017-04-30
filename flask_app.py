# -*- coding: utf-8 -*-
from pprint import pprint as pp
import pdb
from flask import Flask, session, redirect, render_template, request, url_for, Response
from flask_admin import Admin
from sqlalchemy import *
import sqlalchemy.sql
import sqlalchemy
#from flask_sqlalchemy import SQLAlchemy
import datetime, sys, re, json
from collections import Counter
from random import choice, shuffle
import yaml

app = Flask(__name__)
app.config["DEBUG"] = True
admin = Admin(app, name='enbugstuff', template_mode='bootstrap3', url='/0d20f554eb0bf160df9ef424a1a1b436')


# SQL stuff:
metadata = MetaData()
snippets = Table("snippets", metadata,
    Column("id", Integer, primary_key=True),
    Column("text", Text, nullable=False, default="")
)
votes = Table("votes", metadata,
    Column("id", Integer, primary_key=True),
    Column("snippet_id", Integer, nullable=False, index=True),
    Column("positive", Boolean, nullable=False, index=True),
    Column("votername", String(128), index=True),
    Column("created_at", Date, default=datetime.datetime.now),
    Column("updated_at", Date, onupdate=datetime.datetime.now),
    Column("approximate_user_identifier", String(128))
)

comments = Table("comments", metadata,
    Column("id", Integer, primary_key=True),
    Column("snippet_id", Integer, nullable=False, index=True),
    Column("votername", String(128), index=True),
    Column("created_at", Date, default=datetime.datetime.now),
    Column("text", Text, nullable=False, default="")
)


SQLALCHEMY_DATABASE_URI = "mysql+mysqlconnector://{username}:{password}@{hostname}/{databasename}?charset=utf8mb4".format(
    username="enbug",
    password="rqnyfdztwutldbkwvhwk",
    hostname="enbug.mysql.pythonanywhere-services.com",
    databasename="enbug$project",
)
app.config["SQLALCHEMY_DATABASE_URI"] = SQLALCHEMY_DATABASE_URI
app.config["SQLALCHEMY_POOL_RECYCLE"] = 10

engine = create_engine(SQLALCHEMY_DATABASE_URI)
metadata.create_all(engine)

#db = SQLAlchemy(app)
#from flask_app import db
#db.create_all()
#conn = engine.connect()

app.secret_key = 'gbxtqmypswnohyatyulm'

#todo:
# - only show undownvoted snippets
# - don't show the same snippet twice to the same person
# - ask for a name to sign the votes with

@app.route("/name", methods=["POST"])
def name():
    session['name'] = request.form["name"]
    return redirect(url_for('index'))

def get_weights():
    try:
        conn = engine.connect()
        pubs = ["Guillaume Morrissette", "", "Emily CA", "Rhiannon Collett", "André", "Klara Du Plessis", "blare coughlin"]
        votes = Counter(v[0] for v in conn.execute("select votername from votes"))
        weights = {
            voter:
                (2 if voter in pubs else 0.5) *
                (2 ** (votes[voter]/70))
            for voter in votes.keys()
            }
        return weights
    finally:
        conn.close()

def best_to_worst(snippets, conn):
    weights = get_weights()
    def foo(k):
        votes_here = conn.execute(sqlalchemy.sql.text('''select * from votes where snippet_id=:id'''), id=k.id)
        rank = -sum(weights[vote.votername]*(vote.positive*2-1) for vote in votes_here)
        return rank
    return sorted(snippets, key=foo)

@app.route("/", methods=["GET", "POST"])
def index():
    if 'name' not in session:
        return render_template("name.html")
    conn = engine.connect()
    try:
        if request.method == "GET":
            query = sqlalchemy.sql.text('''SELECT * FROM snippets
            WHERE NOT EXISTS
            (SELECT * FROM votes WHERE
                   (votes.snippet_id = snippets.id
                   AND (votes.positive=0 OR votes.votername = :name)));
            ''')  # where not voted-upon
             #where exists vote.positive="+ "0" if get_best(wc_only=True) > 10000 else "1"+" and vote.id...
            snippets_to_vote_on = list(conn.execute(query, name=session['name']))
            if len(snippets_to_vote_on) == 0:
                return '<p>you have voted on everything!</p>'
            weights = get_weights()
            snippets_to_vote_on.sort(
                key = lambda snip:sum(
                    weights[vote.votername] for vote in
                    conn.execute(sqlalchemy.sql.text("select * from votes where snippet_id=:id"),id=snip.id)
                )
            )
            snippet = snippets_to_vote_on[0]


            ##  stats
            voter_stats = Counter(name[0] for name in conn.execute("select votername from votes"))
            ranks = [pair[0] for pair in voter_stats.most_common()]

            totalvotes = sum(voter_stats.values())
            voteless = "n/a"
            Counter([vote.snippet_id for vote in conn.execute("select * from votes")]).most_common()[-1]
            upvotes = str(float(list(conn.execute(
                "SELECT SUM(positive) FROM votes"))[0][0])*100/totalvotes
                ) + "%"
            yourvotecount = Counter(
                item[0] for item in conn.execute(
                    sqlalchemy.sql.text(
                            "SELECT positive FROM votes WHERE votername = :name"),
                            name=session['name'])
                    )
            scoreboard = "out of {} voters, you are #{}".format(len(voter_stats.keys()),
             (ranks.index(session["name"]) if session["name"] in ranks else "unranked"))
            yourvotes = "you, {}, have voted {} yep, {} nop - {}% positivity".format(
                session['name'],
                yourvotecount[1],
                yourvotecount[0],
                100*float(yourvotecount[1])/sum(yourvotecount.values()) if yourvotecount else "n/a"
            )
            return render_template("main.html", passage=snippet.text, id=snippet.id, scoreboard=scoreboard, totalvotes=totalvotes, unvoted=voteless, upvotes=upvotes, yourvotes=yourvotes)
        vote = (request.form["vote"] == "True")
        snippet_id = request.form["snippet_id"]
        sys.stderr.write("hi {} {}".format(vote, snippet_id))
        ins = votes.insert().values(snippet_id=snippet_id, positive=vote, votername = session['name'])
        conn.execute(ins)
        comment = request.form["comment"]
        if comment:
            ins = comments.insert().values(snippet_id=snippet_id, votername=session['name'], text=comment)
            conn.execute(ins)
        return redirect(url_for('index'))
    finally:
        conn.close()


@app.route("/updatesnippet", methods=["GET", "POST"])
def updatesnippet():
    conn = engine.connect()
    try:
        if request.method == "GET":
            snippets = conn.execute('''
            SELECT
            snippets.id AS id,
            snippets.text AS text,
            (SELECT COUNT(*) FROM votes WHERE snippets.id = votes.snippet_id) AS votecount,
            (SELECT COUNT(*) FROM votes WHERE snippets.id = votes.snippet_id AND votes.positive = 1) AS upvotecount,
            (SELECT COUNT(*) FROM votes WHERE snippets.id = votes.snippet_id AND votes.positive = 0) AS downvotecount,
            (SELECT COUNT(*) FROM comments WHERE snippets.id = comments.snippet_id) AS commentcount
            FROM snippets
            ORDER BY (upvotecount + commentcount - downvotecount) DESC
            ;''')
            return render_template("updatesnippet.html", snippets = snippets)
        snippetid = int(request.form["id"])
        newtext = request.form["text"]
        conn.execute(sqlalchemy.sql.text(
                            "UPDATE snippets SET text=:text WHERE id=:id"), text=newtext, id=snippetid)
    finally:
        conn.close()
    return redirect(url_for('updatesnippet'))



@app.route("/addsnippet", methods=["GET", "POST"])
def addsnippet():
    if request.method == "GET":
        return render_template("addsnippet.html")
    #ins = snippets.insert().values(text = request.args.get("text"))
    conn = engine.connect()
    try:
        for section in request.form["text"].split("%["):
            title, section = section.split("\n", 1)
            sys.stderr.write(title)
            for snippet in section.split("%split%"):
                snippet = snippet.strip() + "\n[day " + title + "]"
                ins = snippets.insert().values(text = snippet)
                conn.execute(ins)
    finally:
        conn.close()
    return redirect(url_for('index'))


@app.route("/downloadjson", methods=["GET"])
def downloadjson():
    return Response(jsonize(), mimetype='application/json; charset=utf-8')

@app.route("/uploadjson", methods=["GET", "POST"])
def uploadjson():
    if request.method == "GET":
        return render_template("uploadjson.html")
    newstuff = json.loads(request.form["json"])
    conn = engine.connect()
    try:
        updatecount = 0
        for newthing in newstuff:
            snippetid = newthing[0]
            newtext = newthing[1]
            updatecount += conn.execute(
                    sqlalchemy.sql.text(
                            "UPDATE snippets SET text=:newtext WHERE id=:id AND text != :newtext"),
                        id=snippetid, newtext=newtext
                    ).rowcount
        return redirect(url_for('uploadjson') + '?were_updated_count=' + str(updatecount))
    finally:
        conn.close()

def jsonize():
    return json.dumps(hierarchize(), indent=4, ensure_ascii=False)

def yamlize():
    return yaml.dump(hierarchize())

def hierarchize():
    conn  = engine.connect()
    try:
        snippets = list(conn.execute('''
                SELECT
                snippets.id AS id,
                snippets.text AS text,
                (SELECT COUNT(*) FROM votes WHERE snippets.id = votes.snippet_id) AS votecount,
                (SELECT COUNT(*) FROM votes WHERE snippets.id = votes.snippet_id AND votes.positive = 1) AS upvotecount,
                (SELECT COUNT(*) FROM votes WHERE snippets.id = votes.snippet_id AND votes.positive = 0) AS downvotecount,
                (SELECT COUNT(*) FROM comments WHERE snippets.id = comments.snippet_id) AS commentcount
                FROM snippets
                ORDER BY (upvotecount + commentcount - downvotecount) DESC
                ;'''))
        snippets = best_to_worst(snippets, conn)
        datas = (
            [
            [
                snippet.id,
                snippet.text.replace('\r', ''),
                [
                [vote.id, vote.votername, vote.positive]
                for vote in conn.execute(sqlalchemy.sql.text("select * from votes where snippet_id=:id"), id=snippet.id)
                ],
                [
                [comment.id, comment.votername, comment.text.replace('\r', '')]
                for comment in conn.execute(sqlalchemy.sql.text("select * from comments where snippet_id=:id"), id=snippet.id)
                ]
                ]
            for snippet in snippets
            ]
            )
        return datas
    finally:
        conn.close()

def get_best(threshold=1):
    conn  = engine.connect()
    try:
        snippets = list(conn.execute('''
                SELECT
                snippets.id AS id,
                snippets.text AS text,
                (SELECT COUNT(*) FROM votes WHERE snippets.id = votes.snippet_id) AS votecount,
                (SELECT COUNT(*) FROM votes WHERE snippets.id = votes.snippet_id AND votes.positive = 1) AS upvotecount,
                (SELECT COUNT(*) FROM votes WHERE snippets.id = votes.snippet_id AND votes.positive = 0) AS downvotecount,
                (SELECT COUNT(*) FROM comments WHERE snippets.id = comments.snippet_id) AS commentcount
                FROM snippets
                ORDER BY (upvotecount + commentcount - downvotecount) ASC
                ;'''))
        snippets = list(reversed(best_to_worst(snippets, conn)))
        output = []
        wc = 0
        while wc < 10000 and (snippets[-1].upvotecount-snippets[-1].downvotecount) > int(threshold):
            output.append(snippets.pop().text)
            wc += len(output[-1].split())
        output.sort(key=lambda x:len(x))
        mid = len(output)//2
        o_1 = output[:mid]
        o_2 = output[mid:]
        shuffle(o_1)
        shuffle(o_2)
        output = list(sum(zip(o_1, o_2+[0]), ())[:-1])
        output.insert(0, "word count: " + str(wc))
        return output
    finally:
        conn.close()

@app.route("/best")
def best():
    threshold =request.args.get("threshold", 1)
    output = get_best(threshold)
    return "<html><body><div style=\"margin:auto;width:600px\">" + "\n\n".join(output).replace("\n", " <br/> ") + "</div></body><html>"



@app.route("/admin")
def admin():
    query = "SELECT * FROM snippets JOIN votes ON snippets.id = votes.snippet_id"
    conn = engine.connect()
    try:
        voterstats = []
        weights = get_weights()
        for voter in weights.keys():
            yourvotecount = Counter(
                item[0] for item in conn.execute(
                    sqlalchemy.sql.text(
                            "SELECT positive FROM votes WHERE votername = :name"),
                            name=voter)
                    )

            voterstats.append("{} - weight {} - has commented {} times and voted {} times, {}% positivty".format(
                voter if voter else "adam zachery",
                weights[voter],
                list(conn.execute(sqlalchemy.sql.text("select count(*) from comments where votername = :name"), name=voter))[0][0],
                sum(yourvotecount.values()),
                100*float(yourvotecount[1])/sum(yourvotecount.values()) if yourvotecount else "n/a"
            ))
        votes = conn.execute(query)

        comments = list(conn.execute("""SELECT snippets.text AS passage, comments.text AS comment, comments.votername AS author FROM
                    snippets JOIN comments ON snippets.id = comments.snippet_id"""))
    finally:
        conn.close()
    return render_template("admin.html", voterstats=voterstats, votes=votes, comments=comments)

def splitstuff():
    minidb = []
    for section in open("shitpostsfinal.txt").read().split("%["):
        if section:
            title, section = section.split("\n", 1)
            sys.stderr.write(title)
            for snippet in section.split("%split%"):
                snippet = snippet.strip() + "\n[day " + title + "]"
                #ins = snippets.insert().values(text = snippet)
                #conn.execute(ins)
                minidb.append(snippet)

    return minidb


def conn():
    conn = engine.connect()
    def execute(command, flat=True):
        out = list(conn.execute(command))
        if len(out[0]) == 1:
            out = [item[0] for item in out]
        return out
    return execute

def collapse_whitespace(t):
    return re.sub(r'[ \r\n\t]+', ' ', t).strip()

def simplify_text_for_search(t):
    return collapse_whitespace(re.sub(r'^%\[.*|\[day [^\r\n]*\]', '', t))

def snippet_is_broken(t):
    return not re.search(r'\[day [^\r\n]*\]', t)

def duplicates():
    conn = engine.connect()
    try:
        snippets = list(conn.execute('SELECT * FROM snippets'))
        replacements = []
        for snippet in snippets:
            if snippet_is_broken(snippet.text):
                searchfor = simplify_text_for_search(snippet.text)
                replacement = None
                toomanyduplicates = False
                for s2 in snippets:
                    if (s2.id != snippet.id and not snippet_is_broken(s2.text)
                            and searchfor == simplify_text_for_search(s2.text)):
                        if replacement == None:
                            replacement = s2
                            #print(snippet.id, s2.id, "<<", snippet.text, ">> {{", s2.text, "}}")
                        else:
                            print("more than one duplicate", snippet.id, replacement.id, s2.id)
                            toomanyduplicates = True
                if replacement != None and not toomanyduplicates:
                    replacements.append({"oldid": snippet.id, "oldtext": snippet.text,
                                        "newid": replacement.id, "newtext": replacement.text})
                    print(replacements[-1])
        print('updating', len(replacements))
        #sqlalchemy or mysql won't let me execute them together?
        for r in replacements:
            print(r["oldid"], r["newid"])
            #print(r[0]["id"], r[1]["id"]) #, "<<", r[0]["text"], ">> {{", r[1]["text"], "}}")
            conn.execute(sqlalchemy.sql.text("UPDATE votes SET votes.snippet_id = :newid WHERE votes.snippet_id = :oldid"),
                newid=r["newid"], oldid=r["oldid"])
            conn.execute(sqlalchemy.sql.text("UPDATE comments SET comments.snippet_id = :newid WHERE comments.snippet_id = :oldid"),
                newid=r["newid"], oldid=r["oldid"])
            conn.execute(sqlalchemy.sql.text("DELETE FROM snippets WHERE snippets.id = :oldid"),
                oldid=r["oldid"])
    finally:
        conn.close()


"""
collapse_whitespace = lambda t: re.sub(r'[ \r\n\t]+', ' ', t)
search = lambda term, seq:[item for item in seq if collapse_whitespace(term) in collapse_whitespace(item[1])]
txt = splitstuff()
e = conn()
sql = enumerate(e('select text from snippets where text like "%[days%"'))
def find_index(index, src=txt, trgt=sql):
    term = src[index][1]
    l = len(term)
    return search(term[l//3:2*l//3], trgt)
   """

"""
if (doesn't have suffix) and (there's snippet with a different id and part of the same text that does have a suffix):
    for each vote with this snipet id, update the vote's id to the new snippet
    delete the suffexless one.
    """
