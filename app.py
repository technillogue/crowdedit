# -*- coding: utf-8 -*-
# TODO: move weight calculation to when the vote is made
# figure out how to COUNT
# use relational ORDER BY SUM SELECT WEIGHT FROM VOTES



import datetime
import sys
import re
import json
from collections import Counter
from random import shuffle, randint
from flask import Flask, session, redirect, render_template, request, url_for, Response
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import or_, not_, exists
from sqlalchemy.orm import aliased
from sqlalchemy.sql.expression import func

from sqlalchemy import *
import sqlalchemy.sql
import sqlalchemy


IMPORTANT_NAMES = [
    u"Guillaume Morrissette",
    u"Emily CA",
    u"Rhiannon Collett",
    u"André",
    u"Klara Du Plessis",
    u"blare coughlin"
]


app = Flask(__name__)
app.config["DEBUG"] = True

if app.config["DEBUG"]:
    from pprint import pprint as pp

##### SQLAlcehmy SQL stuff:
metadata = MetaData(schema="crowdedit")
snippets = Table("snippets", metadata,
    Column("id", Integer, primary_key=True),
    Column("text", Text, nullable=False, default="")
)
votes = Table("votes", metadata,
    Column("id", Integer, primary_key=True),
    Column("snippet_id", Integer, nullable=False, index=True),
    Column("valence", Boolean, nullable=False, index=True),
    Column("user", String(128), index=True),
    Column("created_at", Date, default=datetime.datetime.now),
)

comments = Table("comments", metadata,
    Column("id", Integer, primary_key=True),
    Column("text", Text, nullable=False, default=""),
    Column("snippet_id", Integer, nullable=False, index=True),
    Column("user", String(128), index=True),
    Column("created_at", Date, default=datetime.datetime.now),
)


OLD_SQLALCHEMY_DATABASE_URI = "mysql+mysqlconnector://{username}:{password}@{hostname}/{databasename}?charset=utf8mb4".format(
    username="enbug",
    password="rqnyfdztwutldbkwvhwk",
    hostname="localhost",#"enbug.mysql.pythonanywhere-services.com",
    databasename="enbug$project",
)

##########3

SQLALCHEMY_DATABASE_URI = "postgres+psycopg2://{username}:{password}@{hostname}/{databasename}".format(
    username="enbug",
    hostname="localhost",
    password="local",
    databasename="postgres",
)
app.config["SQLALCHEMY_DATABASE_URI"] = SQLALCHEMY_DATABASE_URI
app.config["SQLALCHEMY_POOL_RECYCLE"] = 10
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

engine = create_engine(SQLALCHEMY_DATABASE_URI, client_encoding='utf8')
metadata.create_all(engine)

db = SQLAlchemy(app)


#UPDATE public.user SET activity_count = (select count(*) from vote where vote.user_id = "user".id) + (select count(*) from comment where comment.user_id="user".id);


class Snippet(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    text =  db.Column(db.Text, nullable=False)

    def __repr__(self):
        return "<Snippet {} '{}'>".format(
            self.id,
            self.text[:30].replace("\n", " ")
        )

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.Text, nullable=False, index=True)
    activity_count = db.Column(db.Integer, default=0)

    def __repr__(self):
        return "<User #{}, {}>".format(self.id, self.name)

    def vote(self, valence, snippet_id):
        weight = 1.8 / (1 + 2**-((self.activity_count - 12)/14))
        # sigmoid function, ranges from 0.6 to 1.8,
        # halfway point of 1.2 when a user has voted 28 times.
        if self.name in IMPORTANT_NAMES:
            weight += 0.5
        vote = Vote(
            valence=valence,
            user_id=self.id,
            snippet_id=snippet_id,
            weight=weight
        )
        db.session.add(vote)
        app.logger.info("user {} voted {} on snippet {}, weight {}".format(
            session["user_name"],
            valence,
            snippet_id,
            weight
        ))
        self.activity_count += 1

    def comment(self, text, snippet_id):
        pass


class Vote(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    valence = Column(db.Boolean, nullable=False, index=True)
    snippet_id = db.Column(
        db.Integer,
        db.ForeignKey("snippet.id"),
        nullable=False,
        index=True
    )
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id"),
        nullable=False,
        index=True
    )
    weight = db.Column(db.Float, default=1.0)
    created_at = db.Column(db.Date, default=datetime.datetime.now)

    def __repr__(self):
        return "<Vote {}: {} on snippet {} by user {}, weight {}".format(
            self.id,
            "+" if self.valence else "-",
            self.snippet_id,
            self.user_id,
            self.weight
        )

class Comment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    text = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.Date, default=datetime.datetime.now)
    snippet_id = db.Column(
        Integer,
        db.ForeignKey("snippet.id"),
        nullable=False,
        index=True
    )
    user_id = db.Column(
        Integer,
        db.ForeignKey("user.id"),
        nullable=False,
        index=True
    )

    def __repr__(self):
        return "<Comment {}: {} on snippet {} by user {}".format(
            self.id,
            self.text[:30].replace("\n", ""),
            self.snippet_id,
            self.user_id
        )

db.create_all()




app.secret_key = 'this is unnecessary'
# we don't validate the user's identity in any way
# they are therefore welcome to tamper with cookie as much as they want


@app.route("/add_snippet", methods=["GET", "POST"])
def add_snippet():
    """
    expects something like "%[title]%\nfirst snippet\n%split%second snippet.."
    works for one snippet as well.
    """
    if request.method == "GET":
        return render_template("add_snippet.html")
    added_snippets = 0
    for section in request.form["text"].split("%["):
        if section:
            if "%[" in request.form["text"]:
                title, section = section.split("\n", 1)
                app.logger.info(title)
            else:
                title = ""
            for text in section.split("%split%"):
                snippet = Snippet(text="{}\n[{}]".format(text.strip(), title))
                db.session.add(snippet)
                added_snippets += 1
                app.logger.info("added snippet!")
    db.session.commit()
    return redirect(url_for("add_snippet") + "?were_added=%s" % added_snippets)


@app.route("/name", methods=["POST"])
def name():
    """
    fills session["user_name"] and session["user_id"], raises an exception if
    there are multiple users with one name.
    current behavior is to assume that everyone is who they claim to be
    and a new user inputting the same username is actually the previous user
    """
    session["user_name"] = request.form["name"]
    name_count = User.query.filter(User.name == session["user_name"]).count()
    if name_count == 0:
        user = User(name=session["user_name"])
        db.session.add(user)
        db.session.commit()
        app.logger.info("new user: {}".format(repr(user)))
    elif name_count == 1:
        user = User.query.filter(User.name == session["user_name"]).one()
        app.logger.info("found user {}".format(repr(user)))
    else:
        raise Exception("can't have more than one user with the same name rn")
    session["user_id"] = user.id
    return redirect(url_for('index'))

@app.route("/debug")
def debug():
    raise Exception


@app.route("/", methods=["GET", "POST"])
def index():
    if "user_name" not in session: # refactor as user_id
        return render_template("name.html")
    current_user = User.query.get(session["user_id"])
    if request.method == "GET":
        # the most common version of this query goes
        #SELECT snippet.id
        #FROM snippet
        #LEFT OUTER JOIN vote AS personal on personal.snippet_id = snippet.id AND personal.user_id=1
        #JOIN vote ON vote.snippet_id = snippet.id
        #WHERE personal.id IS NULL
        #GROUP BY snippet.id
        #ORDER BY sum(vote.weight);
        if not request.args.get("repeat_vote", "") == "1":
            query = Snippet.query.filter(
                ~exists().where(
                    and_(
                        Vote.snippet_id == Snippet.id,
                        Vote.user_id == current_user.id
                    )
                ).label("votes")
            )
        if app.config["DEBUG"]:
            expected_snippets = (
                Snippet.query.count()
                - Vote.query.filter(Vote.user_id==current_user.id).count()
            )
            actual_snippets = query.count()
            app.logger.info("expected {}, actually {}".format(
                expected_snippets,
                actual_snippets
            ))
            assert (actual_snippets == expected_snippets)
        else:
            query = Snippet.query
        if request.args.get("random_order", "") == "1":
            query = query.order_by(func.random())
        else:
            vote_alias = aliased(Vote, name="vote_alias")
            query = query.join(vote_alias).group_by(Snippet.id).order_by(
                func.sum(vote_alias.weight)
                )
        snippet = query.first()
        app.logger.info(
            "for user {} '{}', selected snippet {} out of {} remaining".format(
                current_user.id,
                current_user.name,
                snippet.id,
                query.count()
            )
        )
        if snippet is None:
            return "<p> you have voted on every snippet! </p>"
        else:
            average_activity = User.query.with_entities(
                    func.sum(User.activity_count)
                ).scalar() / float(User.query.count())
            yep_count = Vote.query.filter(
                    Vote.user_id==current_user.id,
                    Vote.valence==True
                ).count()
            nop_count = Vote.query.filter(
                    Vote.user_id==current_user.id,
                    Vote.valence==False
                ).count()
            stats = [
                "you, user #{}, {}, have voted and commented {} times".format(
                        current_user.id,
                        current_user.name,
                        current_user.activity_count
                    ),
                "the average user has voted and commented {} times".format(
                        average_activity
                    ),
                "you have voted {} yep and {} nop, {}% positivity".format(
                        yep_count,
                        nop_count,
                        int(100 * yep_count / float(yep_count + nop_count))
                    ),
                "{} snippets that you can vote on remain".format(
                        query.count()
                    ),
            ]
            return render_template(
                "main.html",
                passage=snippet.text,
                id=snippet.id,
                stats=stats
            )
    valence = (request.form["vote"] == "True")
    snippet_id = request.form["snippet_id"]

    current_user.vote(valence, snippet_id)
    comment_text = request.form["comment"]
    if comment_text:
        current_user.comment(comment_text, snippet_id)
        comment = Comment(
            snippet_id=snippet_id,
            user_id=current_user.id,
            text=comment_text
        )
    db.session.commit()
    return redirect(url_for('index'))



def get_rank(snippet, conn, weights, return_weight=False):
    votes_here = conn.execute(sqlalchemy.sql.text('''select * from votes where snippet_id=:id'''), id=snippet.id)
    total_weight = 0
    total_valence = False
    for vote in votes_here:
        weight = weights[vote.user]
        total_valence += {0:-1, 1:1}[vote.valence] * weight
        total_weight += weight
    try:
        rank = total_valence / (total_weight)**0.1
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


def jsonize():
    return json.dumps(hierarchize(), indent=4, ensure_ascii=False)

#def yamlize():
#    return yaml.dump(hierarchize())

def hierarchize():
    conn  = engine.connect()
    try:
        snippets = list(conn.execute('''
                SELECT
                snippets.id AS id,
                snippets.text AS text,
                (SELECT COUNT(*) FROM votes WHERE snippets.id = votes.snippet_id) AS votecount,
                (SELECT COUNT(*) FROM votes WHERE snippets.id = votes.snippet_id AND votes.valence = True) AS upvotecount,
                (SELECT COUNT(*) FROM votes WHERE snippets.id = votes.snippet_id AND votes.valence = False) AS downvotecount,
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
                [vote.id, vote.user, vote.valence]
                for vote in conn.execute(sqlalchemy.sql.text("select * from votes where snippet_id=:id"), id=snippet.id)
                ],
                [
                [comment.id, comment.user, comment.text.replace('\r', '')]
                for comment in conn.execute(sqlalchemy.sql.text("select * from comments where snippet_id=:id"), id=snippet.id)
                ]
                ]
            for snippet in snippets
            ]
            )
        return datas
    finally:
        conn.close()


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

def vote(snippet_id, valence=True, user="em"):
    c('insert into votes (snippet_id, valence, user) values (%s, %s, "%s");' % (snippet_id, valence, user))

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


def get_best(threshold=1, scores=False, goal_wc=10000):
    conn  = engine.connect()
    try:
        snippets = list(conn.execute("SELECT id, text FROM snippets"))
        '''
                SELECT
                snippets.id AS id,
                snippets.text AS text,
                (SELECT COUNT(*) FROM votes WHERE snippets.id = votes.snippet_id) AS votecount,
                (SELECT COUNT(*) FROM votes WHERE snippets.id = votes.snippet_id AND votes.valence = True) AS upvotecount,
                (SELECT COUNT(*) FROM votes WHERE snippets.id = votes.snippet_id AND votes.valence = False) AS downvotecount
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
            (SELECT COUNT(*) FROM votes WHERE snippets.id = votes.snippet_id AND votes.valence = True) AS upvotecount,
            (SELECT COUNT(*) FROM votes WHERE snippets.id = votes.snippet_id AND votes.valence = False) AS downvotecount,
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







@app.route("/downloadjson", methods=["GET"])
def downloadjson():
    return Response(jsonize(), mimetype='application/json; charset=utf-8')


@app.route("/addjson", methods=["GET", "POST"])
def addjson():
    if request.method == "GET":
        return render_template("uploadjson.html")
    new_snippets = json.loads(request.form["json"])
    conn = engine.connect()
    try:
        for snippet_id, snippet_text, new_votes, new_comments in new_snippets:
            ins = snippets.insert().values(text=snippet_text)
            sippet_id = conn.execute(ins).inserted_primary_key[0]
            for old_id, user, valence in new_votes:
                conn.execute(votes.insert().values(
                    snippet_id=snippet_id,
                    valence = valence,
                    user = user
                ))
            for old_id, user, comment_text in new_comments:
                conn.execute(comments.insert().values(
                    snippet_id=snippet_id,
                    text = comment_text,
                    user = user
                ))
        return redirect(url_for('addjson') + '?were_updated_count=' + str(len(new_snippets)))
    finally:
        conn.close()

#@app.route("/uploadjson", methods=["GET", "POST"])
#def uploadjson():
#    if request.method == "GET":
#        return render_template("uploadjson.html")
#    snippets = json.loads(request.form["json"])
#    conn = engine.connect()
#    try:
#        updatecount = 0
#        for snippet_id, snippet_text, votes, comments in snippets:
#            snippet_id = newthing[0]
#            updatecount += conn.execute(
#                    sqlalchemy.sql.text(
#                            "UPDATE snippets SET text=:newtext WHERE id=:id AND text != :newtext"),
#                        id=snippet_id, newtext=snippet_text
#                    ).rowcount
#        return redirect(url_for('') + '?were_updated_count=' + str(updatecount))
#    finally:
#        conn.close()

"""
takes [[snippet_id, snippet_text, [[vote_id, user, vote_valence],
...], [comment_id, user, comment], ...]
returns ([snippets], [votes], [comments]
"""

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
                            "SELECT valence FROM votes WHERE user = :name"),
                            name=voter)
                    )
            voterstats.append(
                ((lambda *x:";\t\t".join(x)) if table else ("{} - weight {} - has voted {} times, {}% positivty, and commented {} times".format))(
                *map(str, (
                    voter if voter else "adam zachery",
                    weight,
                    sum(yourvotecount.values()),
                    100*float(yourvotecount[1])/sum(yourvotecount.values()) if yourvotecount else "n/a",
                    list(conn.execute(sqlalchemy.sql.text(u"select count(*) from comments where user = :name"), name=voter.encode("utf-8")))[0][0]
                ))
                )
            )
        votes = conn.execute(query)
        comments = list(conn.execute("""SELECT snippets.text AS passage, comments.text AS comment, comments.user AS author FROM
                    snippets JOIN comments ON snippets.id = comments.snippet_id ORDER BY comments.created_at"""))
    finally:
        conn.close()
    return render_template("admin.html", voterstats=voterstats, votes=votes, comments=comments)

