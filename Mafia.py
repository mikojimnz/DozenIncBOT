#!/usr/bin/pyton3

import datetime
import functools
import json
import os
import math
import mysql.connector
import mysql.connector.pooling
import pickle
import praw
import random
import re
import schedule
import signal
import sys
import time
import traceback

from mysql.connector import errorcode
from mysql.connector.cursor import MySQLCursorPrepared
from random import randrange
from time import sleep

exceptCnt = 0
state = None
curCycle = None

def main():
    global exceptCnt
    global state
    global curCycle

    with open('init/statements.json') as jsonFile1:
        stm = json.load(jsonFile1)
    with open('data/save.json') as jsonFile2:
        sve = json.load(jsonFile2)
    with open('init/settings.json') as jsonFile3:
        cfg = json.load(jsonFile3)

    exceptCnt = 0
    state = sve['state']
    curCycle = sve['curCycle']

    reddit = praw.Reddit(cfg['reddit']['praw'])
    sub = reddit.subreddit(cfg['reddit']['sub'])
    commentStream = sub.stream.comments(skip_existing=True,pause_after=-1)
    inboxStream = reddit.inbox.stream(pause_after=-1)

    db = mysql.connector.pooling.MySQLConnectionPool(pool_name=None, raise_on_warnings=True, connection_timeout=3600, **cfg['sql'])
    pool = db.get_connection()
    con = pool.cursor(prepared=True)

    idCache = []
    itemCache = {}
    lastCmd = ''

    def log_commit(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            username = '*SELF*'
            command = '!CYCLE'
            utc = time.time();

            try:
                if (item != None):
                    username = item.author.name
                    command = item.body
                    utc = item.created_utc

                result = func(*args, **kwargs)
                pattern = re.search(r'^![\w]{1,}\s([\w\d_\-\s/]+)', command)
                readable = time.strftime('%m/%d/%Y %H:%M:%S',  time.gmtime(utc))
                action = ''

                if (result == -1):
                    action += 'FAILED '

                if pattern:
                    action += f'{func.__name__} - {pattern.group(1)}'
                else:
                    action += f'{func.__name__}'

                con.execute(stm['preStm']['log'], (utc, username, action))
                con.execute('COMMIT;')
                print(f'[{readable}] {username}: {action}')
            except mysql.connector.Error as e:
                print(f'SQL EXCEPTION @ {func.__name__} : {args} - {kwargs}\n{e}')
                con.close()
                os._exit(-1)
            return result
        return wrapper

    def game_command(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            pattern = re.search(r'^!([a-z]{4,})\s(?:u/)?([\w\d_\-]+)\s?$', item.body)
            search = ''

            if (state == 0):
                item.reply(stm['err']['notStarted'])
                return -1

            if (func.__name__ != 'burnUser'):
                if pattern:
                    search = pattern.group(2)
                else:
                    item.reply(stm['err']['impFmt'])
                    return -1

            try:
                con.execute(stm['preStm']['chkUsr'], (item.author.name,))
                r = con.fetchall()

                if (len(r) <= 0):
                    item.reply(stm['err']['spec'])
                    return -1

                con.execute(stm['preStm']['chkCmt'], (item.author.name, cfg['commands']['useThreshold']))
                r = con.fetchall()

                if (len(r) <= 0):
                    item.reply(stm['err']['noParticipate'])
                    return -1

                if ((func.__name__ != 'unlockTier') and (func.__name__ != 'burnUser')):
                    con.execute(stm['preStm']['digupUser'], (search,))
                    r = con.fetchall()

                    if (len(r) <= 0):
                        item.reply(stm['err']['notFound'])
                        return -1

                result = func(*args, **kwargs)

            except mysql.connector.Error as e:
                print(f'SQL EXCEPTION @ {func.__name__} : {args} - {kwargs}\n{e}')
                con.close()
                os._exit(-1)
            return result
        return wrapper

    def schdWarn(min=00):
        if (state != 1):
            return -1

        reddit.submission(id=cfg['reddit']['targetPost']).reply(stm['comment']['actions']['schdWarn'].format(min))
        print(f'Cycle Warning {min}')

    def autoCycle():
        global curCycle

        if (state != 1):
            return -1

        with open('data/save.json') as jsonFile2:
            sve = json.load(jsonFile2)

        cycle()
        print(f'Auto Cycle {curCycle}')

    def scheduleJobs():
        schedule.every().day.at(f'{str(cfg["clock"]["hour1"] - 1).zfill(2)}:30').do(schdWarn,min=30)
        schedule.every().day.at(f'{str(cfg["clock"]["hour1"] - 1).zfill(2)}:45').do(schdWarn,min=15)
        schedule.every().day.at(f'{str(cfg["clock"]["hour1"] - 1).zfill(2)}:55').do(schdWarn,min=5)
        schedule.every().day.at(f'{str(cfg["clock"]["hour1"]).zfill(2)}:00').do(autoCycle)

        schedule.every().day.at(f'{str(cfg["clock"]["hour2"] - 1).zfill(2)}:30').do(schdWarn,min=30)
        schedule.every().day.at(f'{str(cfg["clock"]["hour2"] - 1).zfill(2)}:45').do(schdWarn,min=15)
        schedule.every().day.at(f'{str(cfg["clock"]["hour2"] - 1).zfill(2)}:55').do(schdWarn,min=5)
        schedule.every().day.at(f'{str(cfg["clock"]["hour2"]).zfill(2)}:00').do(autoCycle)

        schedule.every().day.at(f'{str(cfg["clock"]["hour1"] - 1 + 12).zfill(2)}:30').do(schdWarn,min=30)
        schedule.every().day.at(f'{str(cfg["clock"]["hour1"] - 1 + 12).zfill(2)}:45').do(schdWarn,min=15)
        schedule.every().day.at(f'{str(cfg["clock"]["hour1"] - 1 + 12).zfill(2)}:55').do(schdWarn,min=5)
        schedule.every().day.at(f'{str(cfg["clock"]["hour1"] + 12).zfill(2)}:00').do(autoCycle)

        schedule.every().day.at(f'{str(cfg["clock"]["hour2"] - 1 + 12).zfill(2)}:30').do(schdWarn,min=30)
        schedule.every().day.at(f'{str(cfg["clock"]["hour2"] - 1 + 12).zfill(2)}:45').do(schdWarn,min=15)
        schedule.every().day.at(f'{str(cfg["clock"]["hour2"] - 1 + 12).zfill(2)}:55').do(schdWarn,min=5)
        schedule.every().day.at(f'{str(cfg["clock"]["hour2"] + 12).zfill(2)}:00').do(autoCycle)

        schedule.every(2).to(5).hours.do(makeComment)
        schedule.every(4).hours.do(refreshConnection)
        print("Jobs Scheduled")

    @log_commit
    def gameState(state):
        global curCycle

        pattern = re.search(r'^!GAMESTATE\s([0-9]{1,1})(\s-[sS])?', item.body)
        setState = int(pattern.group(1))
        silent = pattern.group(2)

        if (item.author.name not in cfg['adminUsr']):
            con.execute(stm['preStm']['log'], (item.created_utc, item.author.name, 'ATTEMPTED ADMIN COMMAND: gameState'))
            return -1
        else:
            if ((setState == 0) and (silent == None)):
                comment = reddit.submission(id=cfg['reddit']['targetPost']).reply(stm['sticky']['pause'])
                comment.mod.distinguish(how='yes', sticky=True)
            elif ((setState == 1) and (silent == None)):
                gameStart()
            elif ((setState == 2) and (silent == None)):
                gameEnd()

            if (item.author.name != '*SELF*'): item.reply(f'**gamestate changed to {setState}**')
            save(setState, curCycle)
            return setState

    @log_commit
    def addUser():
        if (state == 1):
            item.reply(stm['err']['alreadyStarted'])
            return -1

        con.execute(stm['preStm']['chkUsrState'],(item.author.name,))
        r = con.fetchall()

        if(len(r) > 0):
            con.execute(stm['preStm']['addExistingUser'], (cfg['commands']['maxRequests'], item.author.name))
            reddit.submission(id=cfg['reddit']['targetPost']).reply(stm['comment']['actions']['addExistingUser'].format(item.author.name))
        else:
            con.execute(stm['preStm']['addUser'], (item.created_utc, item.author.name))
            reddit.submission(id=cfg['reddit']['targetPost']).reply(stm['comment']['actions']['addUser'].format(item.author.name))

        sub.flair.set(item.author, text=stm['flairs']['alive'], flair_template_id=cfg['flairID']['alive'])
        item.reply(stm['reply']['addUser'].format(item.author.name))
        setItems(item.author.name, item)

    @log_commit
    def removeUser():
        global curCycle

        con.execute(stm['preStm']['removeUser'], (curCycle, item.author.name))
        reddit.submission(id=cfg['reddit']['targetPost']).reply(stm['comment']['actions']['removeUser'].format(item.author.name))
        sub.flair.delete(item.author)
        setItems(item.author.name, None)

    @log_commit
    @game_command
    def voteUser():
        global curCycle

        con.execute(stm['preStm']['unlock'][0], (item.author.name,))
        r = con.fetchall()

        if (r[0][0] < cfg['commands']['unlockVote']):
            item.reply(stm['err']['notUnlocked'])
            return -1

        pattern = re.search(r'^!vote\s(?:u/)?([A-Za-z0-9_]{1,20})', item.body)
        target = pattern.group(1)
        con.execute(stm['preStm']['digupUser'], (target,))
        r = con.fetchall()

        if ((len(r) <= 0) or (r[0][2]) != 1):
            item.reply(stm['err']['notAlive'])
            return -1

        con.execute(stm['preStm']['voteUser'], (item.author.name, target))
        success = con.rowcount

        if ((r[0][1] > cfg['commands']['escapeHit']) and (success > 0)):
            sendMessage(target, stm['reply']['hitAlertEsc'].format(target, curCycle + 1))
            item.reply(stm['reply']['voteUser'])
        elif (success > 0):
            sendMessage(target, stm['reply']['hitAlert'].format(target, curCycle + 1))
            item.reply(stm['reply']['voteUser'])
        else:
            item.reply(stm['err']['voteUser'])
            return -1

    @log_commit
    @game_command
    def burnUser():
        global curCycle

        con.execute(stm['preStm']['unlock'][0], (item.author.name,))
        r = con.fetchall()

        if (r[0][0] < cfg['commands']['unlockBurn']):
            item.reply(stm['err']['notUnlocked'])
            return -1

        if (curCycle < cfg['commands']['burnAfter']):
            item.reply(stm['err']['noBurnYet'])
            return -1

        con.execute(stm['preStm']['chkBurn'], (item.author.name,))
        r = con.fetchall()

        if (len(r) <= 0):
            item.reply(stm['err']['burnUsed'])
            return -1

        tier = r[0][2]
        selfTeam = r[0][1]
        oppTeam = selfTeam + 2
        con.execute(stm['preStm']['burn'][selfTeam], (item.author.name,))
        toBurn = con.fetchall()
        con.execute(stm['preStm']['burn'][oppTeam])
        toReport = con.fetchall()

        if ((len(toBurn) <= 0) or (len(toReport) <= 0)):
            item.reply(stm['err']['noBurnLeft'])
            return -1

        burned = toBurn[random.randint(0, len(toBurn) - 1)][0]
        exposed = toReport[random.randint(0, len(toReport) - 1)][0]
        deathMsg = random.randint(0,len(stm['deathMsg']) - 1)
        con.execute(stm['preStm']['burn'][4], (item.author.name,))
        con.execute(stm['preStm']['burn'][5], (burned,))
        con.execute(stm['preStm']['log'], (time.time(), burned, 'Betrayed'))
        con.execute(stm['preStm']['log'], (time.time(), exposed, 'Exposed'))
        sub.flair.set(reddit.redditor(burned), text=stm['flairs']['dead'].format(stm['deathMsg'][deathMsg], curCycle + 1), flair_template_id=cfg['flairID']['dead'])
        item.reply(stm['reply']['burnUser'].format(burned, exposed, stm['teams'][0][(selfTeam + 1) % 2]))

        if (tier >= cfg['commands']['burnQuietly']):
            sendMessage(burned, stm['reply']['burnedUserQuietly'].format(stm['deathMsg'][deathMsg], curCycle + 1))
            reddit.submission(id=cfg['reddit']['targetPost']).reply(stm['comment']['actions']['burnUserQuietly'].format(burned, stm['deathMsg'][deathMsg]))
        else:
            sendMessage(burned, stm['reply']['burnedUser'].format(stm['deathMsg'][deathMsg], item.author.name, curCycle + 1))
            reddit.submission(id=cfg['reddit']['targetPost']).reply(stm['comment']['actions']['burnUser'].format(burned, stm['deathMsg'][deathMsg], item.author.name,))

    @log_commit
    @game_command
    def reviveUser():
        con.execute(stm['preStm']['unlock'][0], (item.author.name,))
        r = con.fetchall()

        if (r[0][0] < cfg['commands']['unlockRevive']):
            item.reply(stm['err']['notUnlocked'])
            return -1

        con.execute(stm['preStm']['revive'][0], (item.author.name,))
        r = con.fetchall()

        if (len(r) <= 0):
            item.reply(stm['err']['reviveUsed'])
            return -1

        pattern = re.search(r'^!revive\s(?:u/)?([A-Za-z0-9_]{1,20})', item.body)
        target = pattern.group(1)
        con.execute(stm['preStm']['revive'][1], (target,))
        r = con.fetchall()

        if (len(r) <= 0):
            item.reply(stm['err']['alive'])
            return -1

        con.execute(stm['preStm']['revive'][2], (item.author.name,))
        con.execute(stm['preStm']['revive'][3], (target,))
        sub.flair.set(reddit.redditor(target), text=stm['flairs']['alive'], flair_template_id=cfg['flairID']['alive'])
        sendMessage(target, stm['reply']['revivedUser'].format(item.author.name))
        item.reply(stm['reply']['reviveUser'].format(target))
        reddit.submission(id=cfg['reddit']['targetPost']).reply(stm['comment']['actions']['revive'])

    @log_commit
    @game_command
    def digupUser():
        con.execute(stm['preStm']['unlock'][0], (item.author.name,))
        r = con.fetchall()
        tier = r[0][0]

        pattern = re.search(r'^!digup\s(?:u/)?([A-Za-z0-9_]{1,20})', item.body)
        con.execute(stm['preStm']['digupUser'], (pattern.group(1),))
        r = con.fetchall()

        random.seed(time.time())
        role = ''
        maxTeams = len(stm['teams'][0]) - 1
        maxRoles = len(stm['teams'][1][0]) - 1
        cred = ((tier + 1) * 25) - random.randint(0,25)

        if (tier == 0):
            if (random.randint(0,7) == 0):
                role = stm['teams'][0][r[0][0]]
            else:
                role = stm['teams'][0][random.randint(0,maxTeams)]
        elif (tier == 1):
            if (random.randint(0,5) == 0):
                role = stm['teams'][2][r[0][0]][r[0][1]]
            else:
                role = stm['teams'][2][random.randint(0,maxTeams)][random.randint(0,maxRoles)]
        elif (tier >= 2):
            if (random.randint(0,3) == 0):
                role = stm['teams'][2][r[0][0]][r[0][1]]
            else:
                role = stm['teams'][2][random.randint(0,maxTeams)][random.randint(0,maxRoles)]

        item.reply(stm['reply']['digupUser'][0][0].format(pattern.group(1), role, stm['reply']['digupUser'][1][r[0][2]], cred))

    @log_commit
    @game_command
    def locateUser():
        con.execute(stm['preStm']['unlock'][0], (item.author.name,))
        r = con.fetchall()

        if (r[0][0] < cfg['commands']['unlockLocate']):
            item.reply(stm['err']['notUnlocked'])
            return -1

        pattern = re.search(r'^!locate\s(?:u/)?([A-Za-z0-9_]{1,20})', item.body)
        name = pattern.group(1)
        con.execute(stm['preStm']['locateUser'], (name,))
        r = con.fetchall()

        item.reply(stm['reply']['locateUser'].format(name, r[0][0]))

    @log_commit
    @game_command
    def requestUser():
        con.execute(stm['preStm']['unlock'][0], (item.author.name,))
        r = con.fetchall()

        if (r[0][0] < cfg['commands']['unlockRequest']):
            item.reply(stm['err']['notUnlocked'])
            return -1

        con.execute(stm['preStm']['request'][0], (item.author.name,))
        r = con.fetchall()

        if (len(r) <= 0):
            item.reply(stm['err']['noRequestLeft'])
            return -1

        pattern = re.search(r'^!request\s(?:u/)?([A-Za-z0-9_]{1,20})', item.body)
        item.reply(stm['reply']['requestUser'])
        reddit.submission(id=cfg['reddit']['targetPost']).reply(stm['comment']['actions']['requestUser'].format(pattern.group(1), stm['teams'][0][r[0][1]]))
        con.execute(stm['preStm']['request'][1], (item.author.name,))

    @log_commit
    @game_command
    def unlockTier():
        pattern = re.search(r'^![a-z]{4,}\s(?:u/)?([\w\d\-]+)\s?$', item.body)
        code = ''

        if pattern:
            code = pattern.group(1)
        else:
            item.reply(stm['err']['impFmt'])
            return -1

        con.execute(stm['preStm']['unlock'][0], (item.author.name,))
        r = con.fetchall()
        tier = r[0][0]
        team = r[0][1]

        if (tier > len(cfg['codes']) - 1):
            item.reply(stm['err']['maxTier'])
            return -1

        if (cfg['codes'][tier] == code):
            con.execute(stm['preStm']['unlock'][1], (item.author.name,))

            if (tier == cfg['commands']['addRequestsOn']):
                con.execute(stm['preStm']['unlock'][2], (cfg['commands']['addRequests'], item.author.name))
                item.reply(stm['reply']['addRequests'].format(cfg['commands']['addRequests']))

            item.reply(stm['reply']['promote'].format(stm['teams'][1][team][tier + 1]))
            reddit.submission(id=cfg['reddit']['targetPost']).reply(stm['comment']['actions']['promote'].format(tier + 2))
        else:
            item.reply(stm['err']['wrongCode'])
            return -1

    @log_commit
    @game_command
    def switchTeam():
        if (cfg['commands']['allowSwitchTeam'] == 0):
            item.reply(stm['err']['switchTeamDisabled'])
            return -1

        con.execute(stm['preStm']['unlock'][0], (item.author.name,))
        r = con.fetchall()

        if (r[0][0] < cfg['commands']['unlockInviteSwitch']):
            item.reply(stm['err']['notUnlocked'])
            return -1

        pattern = re.search(r'^!convert\s(?:u/)?([A-Za-z0-9_]{1,20})', item.body)
        target = pattern.group(1)
        con.execute(stm['preStm']['digupUser'], (target,))
        r = con.fetchall()

        if ((len(r) <= 0) or (r[0][2]) != 1):
            item.reply(stm['err']['notAlive'])
            return -1

        con.execute(stm['preStm']['switchTeam'][0], (target,))
        r = con.fetchall()

        if (len(r) > 1):
            item.reply(stm['err']['switchTeamBlocked'])
            return -1

        con.execute(stm['preStm']['switchTeam'][1], (item.author.name, target))
        success = con.rowcount

        if (success > 0):
            sendMessage(target, stm['reply']['switchTeamMsg'].format(item.author.name, curCycle + 1))
            item.reply(stm['reply']['switchTeam'])
            reddit.submission(id=cfg['reddit']['targetPost']).reply(stm['comment']['actions']['switchTeamInvite'])
        else:
            item.reply(stm['err']['switchTeam'])
            return -1

    @log_commit
    def acceptInvite():
        if (cfg['commands']['allowSwitchTeam'] == 0):
            item.reply(stm['err']['switchTeamDisabled'])
            return -1

        con.execute(stm['preStm']['switchTeam'][2], (item.author.name,))
        r = con.fetchall()

        if (len(r) <= 0):
            item.reply(stm['err']['switchTeamNone'])
            return -1

        con.execute(stm['preStm']['switchTeam'][3], (r[0][0], r[0][1]))
        con.execute(stm['preStm']['switchTeam'][4], (r[0][1],))
        item.reply(stm['reply']['switchTeamAccept'])
        sendMessage(r[0][0], stm['reply']['switchTeamAccepted'].format(r[0][1]))
        reddit.submission(id=cfg['reddit']['targetPost']).reply(stm['comment']['actions']['switchTeam'])

    @log_commit
    def getList():
        dead = ''
        alive = ''
        deadNum = 0
        aliveNum = 0

        con.execute(stm['preStm']['getList'][0])
        r = con.fetchall()

        for row in r:
            dead += f'\n* u/{row[0]}'
            deadNum += 1

        con.execute(stm['preStm']['getList'][1])
        r = con.fetchall()

        for row in r:
            alive += f'\n* u/{row[0]}'
            aliveNum += 1

        item.reply(stm['reply']['getList'].format(deadNum + aliveNum, deadNum, dead, aliveNum, alive))

    @log_commit
    def getStats():
        global curCycle

        team = 'The Spectators'
        tier = 'Spectator'
        loc = 'Nowhere'
        status = 'not playing'

        con.execute(stm['preStm']['chkUsrState'], (item.author.name,))
        r = con.fetchall()

        if (len(r) == 1):
            team = stm['teams'][0][r[0][0]]
            tier = stm['teams'][2][r[0][0]][r[0][1]]
            loc = r[0][2]
            status = stm['alive'][r[0][3]]

        con.execute(stm['preStm']['cycle']['getAliveCnt'])
        result = con.fetchall()
        alive = result[0][0]
        killed = result[0][1]

        con.execute(stm['preStm']['cycle']['getTeamCnt'])
        result = con.fetchall()
        bad = result[0][0]
        good = result[0][1]

        item.reply(stm['reply']['getSts'][0][0].format(stm['reply']['getSts'][1][state], \
         curCycle + 1, tier, team, loc, status, alive, good, bad, killed, alive + killed, \
         cfg['commands']['burnAfter'], cfg['commands']['voteThreshold'], \
         cfg['commands']['voteOneAfter'], cfg['commands']['maxRequests'], cfg['kickAfter']))

    @log_commit
    def showHelp():
        item.reply(stm['reply']['showHelp'])

    @log_commit
    def showRules():
        item.reply(stm['reply']['showRules'])

    @log_commit
    def makeComment():

        random.seed(time.time())

        if (state == 0):
            reddit.submission(id=cfg['reddit']['targetPost']).reply(stm['comment']['idle'][random.randint(0, len(stm['comment']['idle']) - 1)])
            return

        if (random.randint(0, 2) == 0):
            con.execute(stm['preStm']['cycle']['getVotes'])
            r = con.fetchall()

            if (len(r) <= 0):
                reddit.submission(id=cfg['reddit']['targetPost']).reply(stm['comment']['warn']['noVotes'][random.randint(0, len(stm['comment']['warn']['noVotes']) - 1)])
                return
            else:
                reddit.submission(id=cfg['reddit']['targetPost']).reply(stm['comment']['warn']['votes'][random.randint(0, len(stm['comment']['warn']['votes']) - 1)])
                return

        reddit.submission(id=cfg['reddit']['targetPost']).reply(stm['comment']['spook'][random.randint(0, len(stm['comment']['spook']) - 1)])

    @log_commit
    def gameStart():
        con.execute(stm['preStm']['getPlaying'])
        r = con.fetchall()
        players = len(r)
        curPos = 0

        random.seed(time.time())
        random.shuffle(r)

        for row in r:
            team = curPos % 2

            random.seed(time.time())
            loc = stm['location'][team][random.randint(0, len(stm['location'][team]) - 1)]
            con.execute(stm['preStm']['joinTeam'], (team, loc, row[0]))
            sendMessage(row[0], stm['reply']['gameStart'].format(stm['teams'][0][team], loc, players, cfg['reddit']['sub'], cfg['reddit']['targetPost']))
            curPos += 1
            sleep(0.2)

        comment = reddit.submission(id=cfg['reddit']['targetPost']).reply(stm['sticky']['start'].format(players))
        comment.mod.distinguish(how='yes', sticky=True)

    @log_commit
    def gameEnd():
        global curCycle

        round = curCycle + 1
        con.execute(stm['preStm']['cycle']['resetInactive'])
        con.execute(stm['preStm']['cycle']['incrementInactive'])
        con.execute(stm['preStm']['cycle']['resetComment'])
        con.execute(stm['preStm']['cycle']['getInactive'], (cfg['kickAfter'],))
        r = con.fetchall()

        for row in r:
            sub.flair.delete(reddit.redditor(row[0]))
            reddit.redditor(row[0]).message('You have been kicked!', stm['reply']['cycle'][2])
            sleep(0.2)

        con.execute(stm['preStm']['cycle']['getAliveCnt'])
        r = con.fetchall()
        alive  = r[0][0]
        killed = r[0][1]

        print(f'\nAlive: {alive} | Killed {killed}')

        if (cfg['commands']['allowBotBroadcast'] == 1):
            con.execute(stm['preStm']['getDead'])
            r = con.fetchall()

            for row in r:
                sendMessage(row[0], stm['reply']['gameEnd'].format(cfg['reddit']['sub'], cfg['reddit']['targetPost']))
                sleep(0.2)

        con.execute(stm['preStm']['cycle']['getAlive'])
        r = con.fetchall()

        for row in r:
            if (cfg['commands']['allowBotBroadcast'] == 1):
                sendMessage(row[0], stm['reply']['gameEnd'].format(cfg['reddit']['sub'], cfg['reddit']['targetPost']))

            sub.flair.set(reddit.redditor(row[0]), text=stm['flairs']['survived'].format(stm['teams'][0][row[1]], round), flair_template_id=cfg['flairID']['alive'])
            sleep(0.2)

        con.execute(stm['preStm']['getWinner'])
        r = con.fetchall()
        bad = r[0][0]
        good = r[0][1]

        if (good == bad):
            winner = 'NOBODY'
        elif (good > bad):
            winner = 'MI6'
        else:
            winner = 'The Twelve'

        comment = reddit.submission(id=cfg['reddit']['targetPost']).reply(stm['sticky']['end'].format(winner, alive, killed))
        comment.mod.distinguish(how='yes', sticky=True)

    @log_commit
    def cycle():
        global curCycle

        if (state == 0):
            item.reply(stm['err']['notStarted'])
            return -1

        if (item is None):
            pass
        else:
            if (item.author.name not in cfg['adminUsr']):
                con.execute(stm['preStm']['log'], (item.created_utc, item.author.name, 'ATTEMPTED ADMIN COMMAND: cycle'))
                return -1

        threshold = 1

        if (curCycle > cfg['commands']['voteOneAfter']):
            threshold = 1
        else:
            threshold = cfg['commands']['voteThreshold']

        con.execute(stm['preStm']['cycle']['resetInactive'])
        con.execute(stm['preStm']['cycle']['incrementInactive'])
        con.execute(stm['preStm']['cycle']['resetComment'])
        con.execute(stm['preStm']['cycle']['getInactive'], (cfg['kickAfter'],))
        result = con.fetchall()
        for row in result:
            con.execute(stm['preStm']['log'], (time.time(), row[0], 'Inactive Kick'))
            sub.flair.delete(reddit.redditor(row[0]))
            sendMessage(row[0], stm['reply']['cycle'][2])
            sleep(0.2)

        con.execute(stm['preStm']['cycle']['removeInactive'], (cfg['kickAfter'],))
        con.execute(stm['preStm']['cycle']['getVotes'])
        result = con.fetchall()

        for row in result:
            con.execute(stm['preStm']['chkUsr'], (row[0],))
            r = con.fetchall()
            tier = r[0][2]

            if (tier <= cfg['commands']['escapeHit']):
                continue

            con.execute(stm['preStm']['cycle']['getVoteTarget'], (row[0],))
            target = con.fetchall()

            if (len(target) >= 1):
                con.execute(stm['preStm']['cycle']['getVoters'], (row[0], row[0]))
                list = con.fetchall()

                for user in list:
                    if (target[0][0] == user[0]):
                        con.execute(stm['preStm']['log'], (time.time(), row[0], 'Escaped'))
                        con.execute(stm['preStm']['cycle']['voteEscaped'], (row[0],))
                        sendMessage(row[0], stm['reply']['cycle'][3])
                        print(f'  > {row[0]} escaped')

        con.execute(stm['preStm']['cycle']['killPlayer'], (curCycle, threshold))
        con.execute(stm['preStm']['cycle']['getAliveCnt'])
        result = con.fetchall()
        alive  = result[0][0]
        killed = result[0][1]

        print(f'\nAlive: {alive} | Killed {killed}')

        con.execute(stm['preStm']['cycle']['getTeamCnt'])
        result = con.fetchall()
        bad = result[0][0]
        good = result[0][1]

        print(f'MI6: {good} | The Twelve: {bad}')

        con.execute(stm['preStm']['cycle']['getDead'], (threshold,))
        result = con.fetchall()

        for row in result:
            con.execute(stm['preStm']['cycle']['getKilledMe'], (row[0],))
            r = con.fetchall()
            killedMe = ''

            for v in r:
                killedMe += f'* u/{v[0]}\n'

            random.seed(time.time())
            n = random.randint(0,len(stm['deathMsg']) - 1)
            sub.flair.set(reddit.redditor(row[0]), text=stm['flairs']['dead'].format(stm['deathMsg'][n], curCycle + 1), flair_template_id=cfg['flairID']['dead'])
            sendMessage(row[0], stm['reply']['cycle'][0].format(stm['deathMsg'][n], curCycle + 1, killedMe, alive, good, bad, killed, alive + killed))
            con.execute(stm['preStm']['log'], (time.time(), row[0], 'Killed'))
            print(f'  > {row[0]} killed')
            sleep(0.2)

        con.execute(stm['preStm']['cycle']['getAlive'])
        result = con.fetchall()

        for row in result:
            # sendMessage(row[0], stm['reply']['cycle'][1].format(curCycle + 2, alive, good, bad, killed, alive + killed))
            sleep(0.2)

        con.execute('TRUNCATE TABLE VoteCall');
        con.execute('TRUNCATE TABLE TeamInvite;');
        comment = reddit.submission(id=cfg['reddit']['targetPost']).reply(stm['sticky']['cycle'].format(curCycle + 2, alive, good, bad, killed, alive + killed))
        comment.mod.distinguish(how='yes', sticky=True)

        if (item is None):
            pass
        else:
            item.reply(f'**Moved to Round {curCycle + 2}**')

        print(f'Moved to Round {curCycle + 1}')
        curCycle += 1
        save(state, curCycle)
        return curCycle

    @log_commit
    def broadcast():
        pattern = re.search(r'^!BROADCAST\s([\s\w\d!@#$%^&*()_+{}|:\'<>?\-=\[\]\;\',./’]+)', item.body)
        msg = pattern.group(1)

        if (item.author.name not in cfg['adminUsr']):
            con.execute(stm['preStm']['log'], (item.created_utc, item.author.name, 'ATTEMPTED ADMIN COMMAND: broadcast'))
            return -1

        if (cfg['commands']['allowBotBroadcast'] == 0):
            item.reply('Broadcast Disabled')
            return -1

        con.execute(stm['preStm']['getAll'])
        r = con.fetchall()
        for row in r:
            sendMessage(row[0], msg)
            sleep(0.2)

    @log_commit
    def restart():
        item.mark_read()

        if (item.author.name not in cfg['adminUsr']):
            con.execute(stm['preStm']['log'], (item.created_utc, item.author.name, 'ATTEMPTED ADMIN COMMAND: restart'))
            return -1

        con.execute(stm['preStm']['restart'])
        con.execute('TRUNCATE TABLE VoteCall;');
        con.execute('TRUNCATE TABLE TeamInvite;');
        con.execute('COMMIT;')
        comment = reddit.submission(id=cfg['reddit']['targetPost']).reply(stm['sticky']['restart'])
        comment.mod.distinguish(how='yes', sticky=True)
        save(0, 0)

        if (item.author.name != '*SELF*'): item.reply('**Restarting Game**')
        print('REMOTE RESTART RECEIVED')
        con.close()
        os._exit(1)

    @log_commit
    def reset():
        item.mark_read()

        if (item.author.name not in cfg['adminUsr']):
            con.execute(stm['preStm']['log'], (item.created_utc, item.author.name, 'ATTEMPTED ADMIN COMMAND: reset'))
            return -1

        con.execute('SELECT `username` FROM Mafia')
        r = con.fetchall()

        for row in r:
            sub.flair.delete(row[0])

        con.execute('TRUNCATE TABLE Mafia;');
        con.execute('TRUNCATE TABLE VoteCall;');
        con.execute('TRUNCATE TABLE TeamInvite;');
        con.execute(stm['preStm']['log'], (item.created_utc, item.author.name, 'reset'))
        con.execute('COMMIT;')
        comment = reddit.submission(id=cfg['reddit']['targetPost']).reply(stm['sticky']['reset'])
        comment.mod.distinguish(how='yes', sticky=True)
        save(0, 0)

        try:
            os.remove('data/items.pickle')
        except:
            pass

        if (item.author.name != '*SELF*'): item.reply('**Resetting Game**')
        print('REMOTE RESET RECEIVED')
        con.close()
        os._exit(1)

    @log_commit
    def halt():
        item.mark_read()

        if (item.author.name not in cfg['adminUsr']):
            con.execute(stm['preStm']['log'], (item.created_utc, item.author.name, 'ATTEMPTED ADMIN COMMAND: halt'))
            return -1

        comment = reddit.submission(id=cfg['reddit']['targetPost']).reply(stm['sticky']['halt'])
        comment.mod.distinguish(how='yes', sticky=True)
        con.execute(stm['preStm']['log'], (item.created_utc, item.author.name, 'halt'))
        con.execute('COMMIT;')
        if (item.author.name != '*SELF*'): item.reply('**Stopping Game**')
        print('REMOTE HALT RECEIVED')
        con.close()
        os._exit(1)

    def rateLimit():
        limits = json.loads(str(reddit.auth.limits).replace("'", "\""))

        if (limits['remaining'] < 10):
            reset = (limits["reset_timestamp"] + 10) - time.time()
            print(f'Sleeping for: {reset} seconds')
            print(time.strftime('%m/%d/%Y %H:%M:%S',  time.gmtime(limits["reset_timestamp"])))
            comment = reddit.submission(id=cfg['reddit']['targetPost']).reply(stm['sticky']['rateLimit'].format(reset))
            comment.mod.distinguish(how='yes', sticky=True)
            sleep(reset)

    def sendMessage(name, message):
        if(getItems(name) != None):
            getItems(name).reply(message)
            rateLimit()
        else:
            print(f'WARNING. {name} not found in items.pickle. Falling back on alternate')
            reddit.redditor(name).message('Mafia', message)
            rateLimit()

    def refreshConnection():
        con.execute('SHOW PROCESSLIST;')
        conStat = con.fetchall()
        print(f'Refreshed SQL Connection. {len(conStat)}')

    con.execute(stm['preStm']['main'][0])
    con.execute(stm['preStm']['main'][1], (time.time(),))
    con.execute(stm['preStm']['addDummy'])
    con.execute('COMMIT;')
    con.execute('SHOW PROCESSLIST;')
    conStat = con.fetchall()

    scheduleJobs()

    print(f'Connected as {str(reddit.user.me())}')
    print(f'Database Connections: {len(conStat)}')
    print(f'state: {state}')
    print(f'curCycle: {curCycle} (Cycle: {curCycle + 1})')
    print('______')

    while True:
        schedule.run_pending()

        try:
            for comment in commentStream:
                if comment is None:
                    break

                if ((comment.submission.id == cfg['reddit']['targetPost']) and (comment.id not in idCache)):
                    if (len(idCache) > 1000):
                        idCache = []

                    if(re.search(r'^!(join|leave|vote|digup|rules|help|stats)', comment.body)):
                        comment.reply(stm['err']['notPM'])

                    idCache.append(comment.id)
                    con.execute(stm['preStm']['comment'], (comment.author.name,))
                    con.execute('COMMIT;')

            for item in inboxStream:
                if item is None:
                    break

                if (item.was_comment == True):
                    continue

                if (item.body.strip() == lastCmd):
                    try:
                        con.execute('RESET QUERY CACHE;')
                    except:
                        pass

                with open('data/save.json') as jsonFile2:
                    sve = json.load(jsonFile2)

                state = sve['state']
                curCycle = sve['curCycle']

                if (re.search(r'^!join', item.body)):
                    addUser()
                elif (re.search(r'^!leave', item.body)):
                    removeUser()
                elif (re.search(r'^!vote', item.body)):
                    voteUser()
                elif (re.search(r'^!burn$', item.body)):
                    burnUser()
                elif (re.search(r'^!revive', item.body)):
                    reviveUser()
                elif (re.search(r'^!digup', item.body)):
                    digupUser()
                elif (re.search(r'^!locate', item.body)):
                    locateUser()
                elif (re.search(r'^!request', item.body)):
                    requestUser()
                elif (re.search(r'^!unlock', item.body)):
                    unlockTier()
                elif (re.search(r'^!convert', item.body)):
                    switchTeam()
                elif (re.search(r'^!accept', item.body)):
                    acceptInvite()
                elif ((re.search(r'^!list', item.body))):
                    getList()
                elif (re.search(r'^!stats', item.body)):
                    getStats()
                elif (re.search(r'^!help', item.body)):
                    showHelp()
                elif (re.search(r'^!rules', item.body)):
                    showRules()
                elif (re.search(r'^!GAMESTATE', item.body)):
                    state = gameState(state)
                elif (re.search(r'^!CYCLE', item.body)):
                    curCycle = cycle()
                elif (re.search(r'^!BROADCAST', item.body)):
                    broadcast()
                elif (re.search(r'^!RESTART', item.body)):
                    restart()
                elif (re.search(r'^!RESET', item.body)):
                    reset()
                elif (re.search(r'^!HALT', item.body)):
                    halt()
                else:
                    item.reply(stm['err']['unkCmd'])

                item.mark_read()
                lastCmd = item.body.strip()

        except Exception as e:
            traceback.print_exc()
            exceptCnt += 1
            print(f'Exception #{exceptCnt}\nSleeping for {60 * exceptCnt} seconds')
            sleep(60 * exceptCnt)

    con.close()

def save(state, curCycle):
    with open('data/save.json', 'r+') as jsonFile2:
        tmp = json.load(jsonFile2)
        tmp['state'] = int(state)
        tmp['curCycle'] = int(curCycle)
        jsonFile2.seek(0)
        json.dump(tmp, jsonFile2)
        jsonFile2.truncate()

def setItems(k, v):
    tmp = {}

    try:
        if (os.path.getsize('data/items.pickle') > 0):
            with open('data/items.pickle', 'rb') as itemsFile:
                tmp = pickle.load(itemsFile)
                tmp[k] = v
        else:
            print('WARNING items.pickle not found. Creating new one.')
            tmp[k] = v
    except:
        print('WARNING items.pickle not found. Creating new one.')
        tmp[k] = v
    finally:
        with open('data/items.pickle', 'wb') as itemsFile:
            pickle.dump(tmp, itemsFile)

def getItems(k):
    if os.path.getsize('data/items.pickle') > 0:
        with open('data/items.pickle', 'rb') as itemsFile:
            tmp = pickle.load(itemsFile)
            return tmp[k]
    else:
        print('items.pickle not found. WARNING')
        return None

def exit_gracefully(signum, frame):
    signal.signal(signal.SIGINT, original_sigint)

    try:
        if input('\nDo you really want to quit? (y/n)> ').lower().startswith('y'):
            sys.exit(1)
    except KeyboardInterrupt:
        print('\nQuitting')
        sys.exit(1)

    signal.signal(signal.SIGINT, exit_gracefully)

if __name__ == '__main__':
    original_sigint = signal.getsignal(signal.SIGINT)
    signal.signal(signal.SIGINT, exit_gracefully)
    main()
