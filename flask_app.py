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
from random import shuffle, randint
import yaml

app = Flask(__name__)
app.config["DEBUG"] = True
admin = Admin(app, name='enbugstuff', template_mode='bootstrap3', url='/0d20f554eb0bf160df9ef424a1a1b436')

index_of_last_edited_snippet_in_order_of_rank = 53
#btw = best_to_worst(c("select * from snippets"), engine, True)
#btw[index...]

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
        pubs = ["Guillaume Morrissette", "Emily CA", "Rhiannon Collett", "André", "Klara Du Plessis", "blare coughlin"]
        votes = Counter(v[0] for v in conn.execute("select votername from votes"))
        weights = {
            voter:
                (.4 if voter == "Klara Du Plessis" else -.1) +
                (.4 if voter in pubs else -0.1) +
                1.8 / (1 + 2**-((votes[voter] - 12)/14))  # ranges from 0.4 to 1.6, halfway point of 1 at 28 votes
            for voter in votes.keys()
            }
        return weights
    finally:
        conn.close()

def get_rank(snippet, conn, weights, return_weight=False):
    votes_here = conn.execute(sqlalchemy.sql.text('''select * from votes where snippet_id=:id'''), id=snippet.id)
    total_weight = 0
    total_positive = 0
    for vote in votes_here:
        weight = weights[vote.votername]
        total_positive += {0:-1, 1:1}[vote.positive] * weight
        total_weight += weight
    try:
        rank = total_positive / (total_weight)**0.1
        # this isn't quite a weighted average -- of snippets where 100% of
        # people voted for them, those where more people voted should have
        # higher rankings than those where less people voted. however, this
        # should be scaled down... I might be completely wrong.
    except ZeroDivisionError:
        rank = 0
    return (rank, total_weight) if return_weight else rank

def best_to_worst(snippets, conn, ranked=False):
    weights = get_weights()
    ranks = sorted([
        (get_rank(snippet, conn, weights, ranked), snippet)
        for snippet in snippets
    ], reverse=True)
    if ranked:
        return ranks
    else:
        return list(zip(*ranks))[-1]

@app.route("/", methods=["GET", "POST"])
def index():
    if 'name' not in session:
        return render_template("name.html")
    conn = engine.connect()
    try:
        if request.method == "GET":
            mode = request.args.get("mode", "positive")
            order = request.args.get("order", "least_weight")
            modes = {"positive": "OR votes.positive=0", "all": ""}
            query = sqlalchemy.sql.text('''SELECT * FROM snippets
            WHERE NOT EXISTS
            (SELECT * FROM votes WHERE
                   (votes.snippet_id = snippets.id
                   AND (votes.votername = :name ''' + modes[mode] + ''')));
            ''')  # where not voted-upon
             #where exists vote.positive="+ "0" if get_best(wc_only=True) > 10000 else "1"+" and vote.id...
            snippets_to_vote_on = list(conn.execute(query, name=session['name']))
            if len(snippets_to_vote_on) == 0:
                return '<p>you have voted on everything!</p>'
            weights = get_weights()
            if order == "least_weight":
                snippets_to_vote_on.sort(
                    key = lambda snip:sum(
                        weights[vote.votername] for vote in
                        conn.execute(sqlalchemy.sql.text("select * from votes where snippet_id=:id"),id=snip.id)
                    ) #probably better to refactor this into get_rank
                )
            elif order == "random":
                shuffle(snippets_to_vote_on)
            snippet = snippets_to_vote_on[0]
            # this is could be refactored away; best_to_worst can do this


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
            if section:
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

def get_best(threshold=1, scores=False, goal_wc=10000):
    conn  = engine.connect()
    try:
        snippets = list(conn.execute("SELECT id, text FROM snippets"))
        '''
                SELECT
                snippets.id AS id,
                snippets.text AS text,
                (SELECT COUNT(*) FROM votes WHERE snippets.id = votes.snippet_id) AS votecount,
                (SELECT COUNT(*) FROM votes WHERE snippets.id = votes.snippet_id AND votes.positive = 1) AS upvotecount,
                (SELECT COUNT(*) FROM votes WHERE snippets.id = votes.snippet_id AND votes.positive = 0) AS downvotecount
                FROM snippets
                ORDER BY (upvotecount - downvotecount) ASC
                ;'''# most of it is redundant

        snippets = list(
            filter(
                lambda snippet:snippet[0][0] > float(threshold),
                reversed(best_to_worst(snippets, conn, True))
            )
        ) # worst to best, for efficient popping
        output = []
        wc = 0
        early = []
        end = []
        late = []
        while wc < int(goal_wc) and len(snippets):
            rank, snippet = snippets.pop()
            wc += len(snippet.text.split())
            dest = {3579:end, 3580:late, 2855: early, 2847: early}
            dest.get(snippet.id, output).append(
                snippet.text + "\n[score: {:.3f}/{:.3f}]".format(rank[0], rank[1]) \
                if scores else snippet.text

            )
        # randomize order
        output.sort(key=lambda x:len(x))
        mid = len(output)//2
        o_1 = output[:mid]
        o_2 = output[mid:]
        shuffle(o_1)
        shuffle(o_2)
        for snippet in early:
            #all of these are long
            o_2.insert(
                randint(0, mid//10),
                snippet
            )
        for snippet in late:
            #all [one] of these is short
            o_1.insert(
                randint(-mid//10, -1),
                snippet
            )
        output = list(sum(zip(o_1, o_2+[0]), ())[:-1])
        output.insert(0, "word count: " + str(wc))
        output.extend(end)
        return output
    finally:
        conn.close()

@app.route("/best")
def best():
    threshold =request.args.get("threshold", 0)
    scores=request.args.get("scores", False)
    wc=request.args.get("wc", 10000)
    output = get_best(threshold, scores, wc)
    return "<html><body><div style=\"margin:auto;width:600px\"><p>" + "</p><p>".join(output).replace("\n", " <br/> ") + "</p></div></body><html>"



@app.route("/admin")
def admin():
    table = request.args.get("table")
    query = "SELECT * FROM snippets JOIN votes ON snippets.id = votes.snippet_id ORDER BY votes.created_at"
    conn = engine.connect()
    try:
        voterstats = ["name;\t\tweight;\t\tvotes;\t\tpositivity;\t\tcomments"] if table else []
        weights = get_weights()
        for voter, weight in sorted(weights.items(), key=lambda x:-x[1]):
            yourvotecount = Counter(
                item[0] for item in conn.execute(
                    sqlalchemy.sql.text(
                            "SELECT positive FROM votes WHERE votername = :name"),
                            name=voter)
                    )
            voterstats.append(
                ((lambda *x:";\t\t".join(x)) if table else ("{} - weight {} - has voted {} times, {}% positivty, and commented {} times".format))(
                *map(str, (
                    voter if voter else "adam zachery",
                    weight,
                    sum(yourvotecount.values()),
                    100*float(yourvotecount[1])/sum(yourvotecount.values()) if yourvotecount else "n/a",
                    list(conn.execute(sqlalchemy.sql.text("select count(*) from comments where votername = :name"), name=voter))[0][0]
                ))
                )
            )
        votes = conn.execute(query)

        comments = list(conn.execute("""SELECT snippets.text AS passage, comments.text AS comment, comments.votername AS author FROM
                    snippets JOIN comments ON snippets.id = comments.snippet_id ORDER BY comments.created_at"""))
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
    try:
        execute("select * from snippets where id = 0")
        # the first command will sometimes fail, so this is a dummy command
        # to make sure the connection is working
    except:
        pass
    return execute

def vote(snippet_id, positive=1, votername="em"):
    c('insert into votes (snippet_id, positive, votername) values (%s, %s, "%s");' % (snippet_id, positive, votername))

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
