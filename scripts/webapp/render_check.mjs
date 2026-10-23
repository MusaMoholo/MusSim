// Render the dashboard's tables and charts headlessly and assert on the HTML they produce.
//
//     node scripts/webapp/render_check.mjs <projection.json> <matches.json> <history.json> [<gw.json>|-] [<paths.json>|-] [<track.json>|-] [<team-fixtures.json>|-] [<players.json>|-]
//
// Why this exists. Every serious defect in this app so far rendered PERFECTLY: a header that had
// drifted four columns out of step with its cells labelled the win probability "L", and Arsenal
// showed 75% to lose a match they were favourites in. A syntax check cannot catch that, and
// neither can looking at the page -- the numbers are all real, just under the wrong headings.
//
// So the checks here are accounting identities on the rendered output, not on the source:
//   * every table's <th> count equals every body row's <td> count
//   * the away rows mirror every outcome key, the clean sheet included
//   * a cup's win column sums to 1 and each round's column sums to the size of that round
//   * read off the rendered rows: W + D + L is 100%, W2+ <= W, L2+ <= L and CS <= W + D
//   * every competition in the data gets exactly one tab, in the order GROUPS declares
//   * each history chart draws one line per team and labels its axis in the right unit
//   * given gw.json: the gameweek means balance, a gameweek already played is the real table,
//     and at every gameweek each row's W/D/L is the whole record nearest its means -- for every
//     league AND every UEFA league phase, whose matchday table is the same view
//   * a UEFA finish splits into top 8 / play-off / out, summing to 1 per side and to 8 / 16 / 12
//     sides down the columns
//   * given paths.json: over a knockout round's opponents, P(meet) x P(through | met) sums to the
//     side's chance of going through it, and every rendered path table is square
//   * Position and Points, exactly and at least: every place filled once (a column sums to one
//     side, and at least k-th to k sides), at least a zone's last place is the zone's own chance,
//     at least so many points is the payload's own tail, and a league phase's tails sum to XPTS
//   * the Gameweek view's Title / Down climb round to round and end on TITLE and REL, and a played
//     match's xG beside its score is the step in that side's x+ over the round
//   * fixtures and stakes (version 10): each round's matches once, H + D + A = 100%, a projected
//     match's xG the home side's steps in x+/x− and its x− the away side's x+, each shown swing
//     the widest its stakes allow, the stakes weighted by the results giving back P(fate), the Big
//     matches list in swing order inside its window; Δ columns read the window's own snapshot
//   * ratings (version 5): every league and league-phase side rated exactly once, the average
//     side's ATT equal to its DEF (geometric means over the five leagues), a side the worlds hand
//     the next round unmoved carries today's Elo there, and every chart draws one mark per side
//
// It is invoked by scripts/smoke.py when node is on PATH, and skipped (loudly) when it is not --
// the Python stack stays numpy/pandas-only, so this must never become a hard dependency.
import {readFileSync} from "fs";
import * as Workspace from "./workspace.mjs";
import * as MatchCentre from "./match-centre.mjs";
import * as CompetitionEvidence from "./competition-evidence.mjs";

const [projPath, matchPath, histPath, gwPath, pathsPath, trackPath, teamPath, playerPath, centrePath, clubSourcePath] = process.argv.slice(2);
const ROOT = new URL("./index.html", import.meta.url);
const html = readFileSync(ROOT, "utf8");
const js = html.match(/<script>([\s\S]*)<\/script>/)[1].replace(/\nboot\(\);\s*$/, "\n");

const RESULT = JSON.parse(readFileSync(projPath, "utf8"));
const MATCHES = JSON.parse(readFileSync(matchPath, "utf8"));
const HISTORY = JSON.parse(readFileSync(histPath, "utf8"));
const TEAMD = teamPath && teamPath !== "-" ? JSON.parse(readFileSync(teamPath, "utf8")) : {};
const PLAYERS = playerPath && playerPath !== "-" ? JSON.parse(readFileSync(playerPath, "utf8")) : null;

// A DOM just deep enough for the render paths. Anything the page reaches for that is missing
// throws, which is itself a useful signal, so nothing here is defensive.
const els = {};
const mk = (id) => (els[id] ||= {id, innerHTML: "", textContent: "", hidden: false, children: [],
                                 querySelectorAll: () => [], querySelector: () => null, setAttribute() {}, onchange: null});
globalThis.document = {getElementById: mk, addEventListener() {}};
globalThis.window = globalThis;
globalThis.fetch = async () => { throw new Error("render_check makes no network calls"); };

globalThis.__workspaceServices=Workspace;
try {
await import("data:text/javascript;base64," + Buffer.from(js +
  "\nsetWorkspaceServices(globalThis.__workspaceServices);globalThis.__X = {league, uefa, cup, indexNextFixtures, drawHistory, NEXT_COLS," +
  " get PLAYER_FOCUS(){return PLAYER_FOCUS;}, set PLAYER_FOCUS(v){PLAYER_FOCUS=v;}, playerCardHtml, homeHtml, drawHome, workspaceNavHtml, workspaceEntities, chooseWorkspaceSection, workspacePreferences, followWorkspaceClub, restoreWorkspaceRoute, " +
  " get PLAYER_EVIDENCE_TEAM(){return PLAYER_EVIDENCE_TEAM;},set PLAYER_EVIDENCE_TEAM(v){PLAYER_EVIDENCE_TEAM=v;},playerComparisonHtml,atlasEvidenceHtml,atlasOptions,homePreviewHtml,homeRows,get HOME_MATCH(){return HOME_MATCH;},set HOME_MATCH(v){HOME_MATCH=v;},get HOME_LIMIT(){return HOME_LIMIT;},set HOME_LIMIT(v){HOME_LIMIT=v;},get AGENDA_DATE(){return AGENDA_DATE;},set AGENDA_DATE(v){AGENDA_DATE=v;},get PLAYER_COMPARE(){return PLAYER_COMPARE;},set PLAYER_COMPARE(v){PLAYER_COMPARE=v;},get PLAYER_COMPARE_UNIT(){return PLAYER_COMPARE_UNIT;},set PLAYER_COMPARE_UNIT(v){PLAYER_COMPARE_UNIT=v;},playerOverviewHtml,playerDiscoveryHtml,playerProfilePageHtml,playerSquadPageHtml,get PLAYER_WORKSPACE_VIEW(){return PLAYER_WORKSPACE_VIEW;},set PLAYER_WORKSPACE_VIEW(v){PLAYER_WORKSPACE_VIEW=v;},get PLAYER_SCOPE(){return PLAYER_SCOPE;},set PLAYER_SCOPE(v){PLAYER_SCOPE=v;},get PLAYER_PROFILE_ID(){return PLAYER_PROFILE_ID;},set PLAYER_PROFILE_ID(v){PLAYER_PROFILE_ID=v;},get PLAYER_DISCOVERY_STAT(){return PLAYER_DISCOVERY_STAT;},set PLAYER_DISCOVERY_STAT(v){PLAYER_DISCOVERY_STAT=v;},get PLAYER_DISCOVERY_UNIT(){return PLAYER_DISCOVERY_UNIT;},set PLAYER_DISCOVERY_UNIT(v){PLAYER_DISCOVERY_UNIT=v;},get PLAYER_DISCOVERY_MIN(){return PLAYER_DISCOVERY_MIN;},set PLAYER_DISCOVERY_MIN(v){PLAYER_DISCOVERY_MIN=v;},get PLAYER_QUERY(){return PLAYER_QUERY;},set PLAYER_QUERY(v){PLAYER_QUERY=v;},get PLAYER_SQUAD_TEAM(){return PLAYER_SQUAD_TEAM;},set PLAYER_SQUAD_TEAM(v){PLAYER_SQUAD_TEAM=v;},get PLAYER_SQUAD_METRIC(){return PLAYER_SQUAD_METRIC;},set PLAYER_SQUAD_METRIC(v){PLAYER_SQUAD_METRIC=v;},get PLAYER_TEAM(){return PLAYER_TEAM;},set PLAYER_TEAM(v){PLAYER_TEAM=v;}, clubPool,clubMetricTableHtml,clubSeasonHtml,clubSquadHtml,clubScheduleHtml,clubHistoryHtml,clubComparisonHtml,clubForecastComparisonHtml,clubCentreHtml,clubChartHtml,placesNow,AGENDA_CACHE, get CLUB_SECTION(){return CLUB_SECTION;},set CLUB_SECTION(v){CLUB_SECTION=v;},get CLUB_SCOPE(){return CLUB_SCOPE;},set CLUB_SCOPE(v){CLUB_SCOPE=v;},get CLUB_COMPARE(){return CLUB_COMPARE;},set CLUB_COMPARE(v){CLUB_COMPARE=v;},get CLUB_COMPARE_SCOPE(){return CLUB_COMPARE_SCOPE;},set CLUB_COMPARE_SCOPE(v){CLUB_COMPARE_SCOPE=v;},get CLUB_VENUE(){return CLUB_VENUE;},set CLUB_VENUE(v){CLUB_VENUE=v;},get CLUB_PERIOD(){return CLUB_PERIOD;},set CLUB_PERIOD(v){CLUB_PERIOD=v;},get CLUB_VIEW(){return CLUB_VIEW;},set CLUB_VIEW(v){CLUB_VIEW=v;},get CLUB_CHART(){return CLUB_CHART;},set CLUB_CHART(v){CLUB_CHART=v;},set CLUB_HISTORY(v){CLUB_HISTORY=v;}, set MC(v){MC=v;},workspaceAgendaHtml,centrePreviewHtml,centreImpactHtml,centreChancesHtml, set WORKSPACE(v){WORKSPACE=v;}, get WORKSPACE_SECTION(){return WORKSPACE_SECTION;}, set WORKSPACE_SECTION(v){WORKSPACE_SECTION=v;}, set WORKSPACE_PREFS(v){WORKSPACE_PREFS=v;}, " +
  " COLUMN_PROFILES, overviewRows, overviewColumns, overviewEvidence, metricEvidenceHtml, chooseColumns, OVERVIEW_SORT, get COLUMN_PROFILE(){return COLUMN_PROFILE;}, set COLUMN_PROFILE(v){COLUMN_PROFILE=v;}," +
  " GROUPS, COMP_ORDER, tabGroups, presentComps, roundName, VIEWS, viewsFor, viewOf, trimCup, decidedBy," +
  " HIST_POS, HIST_PTS, HIST_WIN, gwTable, defaultGw, intRecord," +
  " UEFA_VIEWS, UEFA_ZONES, zonesOf, pathsHtml, stageOdds, drawDist, drawPhasePoints," +
  " CUP_VIEWS, pathSpec, roundOdds, drawTrophies, linesStrip," +
  " rivalData, vizRivals, entryRouteData, vizEntryRoutes, timingData, vizTiming, drawRatings, vizHtml, VIZ, VIZOPT, ratingIdx, RATINGS, get BADGES(){return BADGES;}, set BADGES(v){BADGES=v;}, koStages," +
  " chartPickerHtml, chartOpt, chartWindowHtml, chartSettingsHtml, chartHighlightsHtml, wireChartSettings, vizGroups, VIZ_NAMES, ALLVIZ_LIST, heat, heatTip, heatStyle," +
  " get VIZ_SETTINGS_OPEN(){return VIZ_SETTINGS_OPEN;}, set VIZ_SETTINGS_OPEN(v){VIZ_SETTINGS_OPEN=v;}, get VIZ_HIGHLIGHTS_OPEN(){return VIZ_HIGHLIGHTS_OPEN;}, set VIZ_HIGHLIGHTS_OPEN(v){VIZ_HIGHLIGHTS_OPEN=v;}," +
  " get DWIN(){return DWIN;}, set DWIN(v){DWIN=v;}, set DISTMODE(v){DISTMODE=v;}, set RATSEL(v){RATSEL=v;}, set HUBSEL(v){HUBSEL=v;}, set VIZSEL(v){VIZSEL=v;}," +
  " drawStatsHub, drawAllViz, lastFullRound, drawFixtures, drawBigMatches, matchSwing, roundStep, snapAt," +
  " stakeName, cupStakesAvailable, bigMatchRows, cupBigMatchesHtml, nextLine, stakesText," +
  " perWorldQualification, entrySeason, qualificationNote, europeTeam, teamEuropeHtml, sampleEuropeKnown, sampleEurope, lineName," +
  " mobileNavOptions, mobileNavHtml, chooseMobileNav, nativeControl, markKeyboardMode, keyboardAction, wireAccessibility, focusKey, restoreFocus, handleEscape, sortTable, attachTips," +
  " get RENDER(){return render;}, set RENDER(v){render=v;}, get TAB(){return TAB;}, set TAB(v){TAB=v;}, VIEWSEL, MOVERS, PERFORMANCE, TIME_MACHINE, FORECAST_LAB, BIG, TROPHIES, ALLVIZ," +
  " get STUDIO_STATE(){return STUDIO_STATE;}, get MATCH_FOCUS(){return MATCH_FOCUS;}, set MATCH_FOCUS(v){MATCH_FOCUS=v;}, get KEYBOARD_MODE(){return KEYBOARD_MODE;}, set KEYBOARD_MODE(v){KEYBOARD_MODE=v;}," +
  " get LAST_FOCUS(){return LAST_FOCUS;}, set LAST_FOCUS(v){LAST_FOCUS=v;}, get REQUESTED_FOCUS(){return REQUESTED_FOCUS;}, set REQUESTED_FOCUS(v){REQUESTED_FOCUS=v;}," +
  " get TEAM_OPENER(){return TEAM_OPENER;}, set TEAM_OPENER(v){TEAM_OPENER=v;}, get MATCH_OPENER(){return MATCH_OPENER;}, set MATCH_OPENER(v){MATCH_OPENER=v;}," +
  " moversHtml, drawMovers, fillMovers, moveCell, modelName, moversData, chooseMover, MOVERS_CATEGORIES, MOVERS_LIMIT," +
  " get MOVERSEL(){return MOVERSEL;}, set MOVERSEL(v){MOVERSEL=v;}, applyHash, writeHash, get DRAW_MOVERS(){return drawMovers;}, set DRAW_MOVERS(v){drawMovers=v;}," +
  " lineChart, LC," +
  " teamPageHtml, teamFixtures, teamHistoryData, teamHistoryCharts, teamRunIn, teamFormData, teamNextStakes, fixtureRow, vizRI, runInCell," +
  " set TEAM_HCOMP(v){TEAM_HCOMP=v;}, set TEAM_TREND(v){TEAM_TREND=v;}, set TEAM_RATING(v){TEAM_RATING=v;}," +
  " renderTeamCard, get FOCUS(){return FOCUS;}, set FOCUS(v){FOCUS=v;}, get TEAM_PAGE(){return TEAM_PAGE;}, set TEAM_PAGE(v){TEAM_PAGE=v;}," +
  " matchKey, matchFixtures, findMatch, matchXg, matchRecent, matchCardHtml, matchStakesHtml, matchH2hHtml, fixtureCells," +
  " whatifSource, whatifNow, whatifRows, whatifPanelHtml, whatifCardHtml, whatifFixtureButton, whatifFixturesHtml, whatifKey, whatifAvailable, wireWhatif, WHATIF_CARD_OPEN," +
  " get WHATIF_RESULT(){return WHATIF_RESULT;}, get WHATIF_FIXTURE(){return WHATIF_FIXTURE;}, set WHATIF_FIXTURE(v){WHATIF_FIXTURE=v;}," +
  " playersPayload, playersSettled, ensurePlayers, playerCompetition, hasPlayerData, playerRows, playerMetric, playerLeadersData, playerLeadersHtml, teamScorerRows, teamScorersHtml, playerValue, playerBadges," +
  " set PLAYERS(v){PLAYERS=v;}, set PLAYERS_FOR(v){PLAYERS_FOR=v;}, get PLAYERS_STATUS(){return PLAYERS_STATUS;}, set PLAYERS_STATUS(v){PLAYERS_STATUS=v;}, set PLAYERS_PROMISE(v){PLAYERS_PROMISE=v;}," +
  " get PLAYER_METRIC(){return PLAYER_METRIC;}, set PLAYER_METRIC(v){PLAYER_METRIC=v;}, get PLAYER_TEAM(){return PLAYER_TEAM;}, set PLAYER_TEAM(v){PLAYER_TEAM=v;}, get PLAYER_MINUTES(){return PLAYER_MINUTES;}, set PLAYER_MINUTES(v){PLAYER_MINUTES=v;}," +
  " STAKES_OF, STAKE_NAMES, shortName, orient, dwin, windowsOf, GWSEL, get GW(){return GW;}, set GW(v){GW=v;}, set FXMODE(v){FXMODE=v;}, set BIGMODE(v){BIGMODE=v;}," +
  " set RESULT(v){RESULT=v;}, set NEXT(v){NEXT=v;}," +
  " set MATCHES(v){MATCHES=v;}, set HISTORY(v){HISTORY=v;}};").toString("base64"));

const X = globalThis.__X;
X.MC=MatchCentre;
X.COLUMN_PROFILE = "all"; // Existing numerical checks inspect the complete table.
X.RESULT = RESULT;
X.HISTORY = HISTORY;
X.MATCHES = MATCHES;
X.PLAYERS = PLAYERS; X.PLAYERS_FOR = RESULT; X.PLAYERS_STATUS = PLAYERS ? "ready" : "missing";
const NEXT = X.indexNextFixtures(MATCHES);
X.NEXT = NEXT;

let fails = 0;
const check = (ok, label, detail = "") => {
  if (!ok) fails++;
  console.log((ok ? "  ok    " : "  FAIL  ") + label + (ok || !detail ? "" : " — " + detail));
};

// Profile guide: independent same-NET clubs must land on opposite sides of the rising axis.
{
  const services={useBadges:()=>false,badgeOf:()=>null,toneFill:()=>"red",shortName:t=>t,getFocus:()=>null};
  const charts=Workspace.createChartPrimitives(services);
  const pts=[{team:'Attack',x:3,y:2,tip:'Attack'},{team:'Defence',x:2,y:1,tip:'Defence'},
    {team:'Both',x:3,y:1,tip:'Both'},{team:'Neither',x:1,y:3,tip:'Neither'}];
  const markup=charts.scatter(pts,{balance:true,invertY:true,domain:[0,4],xlab:'ATT',ylab:'DEF'});
  const line=markup.match(/<line data-profile-sum="([^"]+)" x1="([^"]+)" y1="([^"]+)" x2="([^"]+)" y2="([^"]+)"/);
  const geometry=m=>m&&Math.abs(+m[1]-4)<1e-12&&Math.abs((+m[2]-64)/1008*4+(+m[3]-18)/550*4-4)<1e-9
    &&Math.abs((+m[4]-64)/1008*4+(+m[5]-18)/550*4-4)<1e-9&&+m[4]>+m[2]&&+m[5]<+m[3];
  check(geometry(line),'Profile guide: both clipped endpoints have ATT+DEF=4 and rise rightwards');
  // Source sums are 5,3,4,4: population variance is (1+1+0+0)/4 = 1/2.
  const outer=[...markup.matchAll(/<line data-profile-sum="([^"]+)" x1="([^"]+)" y1="([^"]+)" x2="([^"]+)" y2="([^"]+)" data-profile-sigma="(-?\d+)"/g)];
  const spreadOK=rows=>rows.length===3&&rows.every(m=>{
    const sum=4+Number(m[6])*Math.sqrt(.5),a=(+m[2]-64)/1008*4+(+m[3]-18)/550*4,b=(+m[4]-64)/1008*4+(+m[5]-18)/550*4;
    return Math.abs(+m[1]-sum)<1e-10&&Math.abs(a-sum)<1e-10&&Math.abs(b-sum)<1e-10&&+m[4]>+m[2]&&+m[5]<+m[3];
  })&&new Set(rows.map(m=>+m[6])).size===3;
  check(spreadOK(outer),'Profile spread: 0/±1 population-SD guides independently reconcile to all clipped endpoints');
  const spreadFault=outer.map(m=>[...m]);spreadFault[1][1]=String(4-Math.sqrt(2/3));
  check(!spreadOK(spreadFault),'Profile spread fault: using sample instead of plotted-population SD is rejected');
  const single=charts.scatter([pts[0]],{balance:true,invertY:true,domain:[0,4],xlab:'ATT',ylab:'DEF'});
  const constant=charts.scatter([pts[0],{...pts[1],x:2,y:3}],{balance:true,invertY:true,domain:[0,4],xlab:'ATT',ylab:'DEF'});
  check([single,constant].every(html=>(html.match(/data-profile-sigma=/g)||[]).length===1&&!html.includes('Profile tilt')&&!/NaN|Infinity/.test(html)),
    'Profile spread: single-club and constant-tilt cohorts show only the balanced guide');
  const fault=[...line];fault[3]=String(+fault[3]+20);
  check(!geometry(fault),'Profile guide deliberate fault: shifted endpoint is rejected');
  const reference={x:2,y:2},attack=Workspace.attackDefenceProfile(3,2,reference),defence=Workspace.attackDefenceProfile(2,1,reference);
  check(3-2===2-1&&attack.lean==='Attack-led profile'&&defence.lean==='Defence-led profile'&&attack.balance===1&&defence.balance===-1,
    'Profile guide: two NET +1 clubs separate by attack and defence contribution');
  const categories=[[3,1,'Stronger on both'],[1,3,'Weaker on both'],[3,3,'Stronger attack, weaker defence'],[1,1,'Stronger defence, weaker attack']];
  check(categories.every(([x,y,label])=>Workspace.attackDefenceProfile(x,y,reference).category===label)
    &&Workspace.attackDefenceProfile(3,1,reference).lean==='Balanced profile', 'Profile guide: four independent quadrant cases and equal improvements');
  check((markup.match(/class="hit"/g)||[]).length===4&&markup.includes('Attack-led profile')&&markup.includes('Defence-led profile'),
    'Profile guide: every source club retains a hit target and profile tooltip');
}

// ---------------------------------------------------------------- tables
// The identity that would have caught the Arsenal/Lille bug on the night it shipped.
for (const [name, markup] of [["league", X.league(RESULT.leagues[0])],
                              ["uefa", X.uefa(RESULT.uefa[0])]]) {
  const rows = markup.split("<tr>").slice(1);
  const heads = (rows[0].match(/<th\b/g) || []).length;
  const cells = [...new Set(rows.slice(1).map((r) => (r.match(/<td\b/g) || []).length))];
  check(cells.length === 1 && cells[0] === heads,
        `${name} table: ${heads} headers == ${cells.join("/")} cells in every body row`,
        `header ${heads}, body row widths ${cells.join("/")}`);
  check(rows.length > 1, `${name} table: has body rows`);
}
// Physical x spacing must follow the numeric fraction, not its index in a union of league ranks.
{
 const block={competition:'Axis audit',teams:[{team:'Axis A'}]},vals=new Map([['Axis A',[0,20,100]]]);
 X.lineChart({block,id:'lcaxisproof',vals,labels:['0','10','100'],positions:[0,10,100]});const c=X.LC.lcaxisproof;
 check(Math.abs((c.X(1)-c.X(0))/(c.X(2)-c.X(0))-.1)<1e-12,'Explore title curve:nonuniform common x positions retain actual numeric spacing');
 let rejected=false;try{X.lineChart({block,id:'lcaxisbad',vals,labels:['0','10','100'],positions:[0,10,5]});}catch{rejected=true;}
 check(rejected,'Explore title curve:out-of-order x position fault rejects');delete X.LC.lcaxisproof;
}
// POS, the place now, in both Overviews: each place once, and never above a side with more points
for (const B of [...RESULT.leagues, ...RESULT.uefa]) {
  const markup = RESULT.leagues.includes(B) ? X.league(B) : X.uefa(B);
  const rows = markup.split("<tr>").slice(1);
  const heads = [...rows[0].matchAll(/<th\b[^>]*>([\s\S]*?)<\/th>/g)].map((m) => m[1].replace(/<[^>]*>/g, "").trim());
  const iP = heads.indexOf("POS"), iT = heads.indexOf("PTS");
  if (iP < 0) { console.log(`  skip    ${B.competition}: no POS (nobody has played)`); continue; }
  const body = rows.slice(1).map((r) => [...r.matchAll(/<td\b[^>]*>([\s\S]*?)<\/td>/g)].map((m) => m[1].replace(/<[^>]*>/g, "").trim()));
  const pos = body.map((c) => +c[iP]).sort((a, b) => a - b);
  const ordered = body.every((a) => body.every((b) => !(+a[iT] > +b[iT] && +a[iP] > +b[iP])));
  check(pos.every((p, k) => p === k + 1) && ordered, `${B.competition} Overview: POS fills each of ${body.length} places once, in points order`);
}

// ---------------------------------------------------------------- cup reach ladders
// Two accounting identities that would catch a miscount long before anyone spotted it by eye:
// exactly one team lifts each cup, and a round's column holds exactly as many teams as the round.
// Both are properties of the COUNTING, so a rendering bug and a simulation bug both show up here.
const CUPS = RESULT.cups || [];
check(CUPS.length > 0, `cup projections present (${CUPS.length})`);
for (const c of CUPS) {
  const shown = X.trimCup(c);
  const rows = X.cup(c).split("<tr>").slice(1);
  const heads = (rows[0].match(/<th\b/g) || []).length;
  const cells = [...new Set(rows.slice(1).map((r) => (r.match(/<td\b/g) || []).length))];
  check(cells.length === 1 && cells[0] === heads,
        `${c.competition}: ${heads} headers == ${cells.join("/")} cells in every body row`,
        `header ${heads}, body row widths ${cells.join("/")}`);
  // Team + one per shown round + Win + its change + the next-tie block (opponent, then NEXT_COLS)
  check(heads === shown.rounds.length + 3 + 1 + X.NEXT_COLS.length,
        `${c.competition}: a column per shown round (${shown.rounds.join(" ")}) plus Team, Win, ±`
        + ` and the next tie`);
  check(rows.length - 1 === shown.teams.length,
        `${c.competition}: one row per surviving team (${shown.teams.length}`
        + ` of ${c.teams.length})`);
  // The trim must never drop a round still in play, nor a team still in the competition.
  check(shown.rounds.length >= 1 && shown.rounds[shown.rounds.length - 1] === "F",
        `${c.competition}: the final survives the trim`);
  check(!shown.teams.some((t) => t["p_" + shown.rounds[0].toLowerCase()] >= 0.9999)
        || shown.rounds.length === 1
        || !shown.teams.every((t) => t["p_" + shown.rounds[0].toLowerCase()] >= 0.9999),
        `${c.competition}: the first shown round is not already decided for everyone`);
  const lostWin = c.teams.filter((t) => !shown.teams.includes(t) && t.p_win > 0);
  check(!lostWin.length, `${c.competition}: no team with a chance of winning was trimmed`,
        lostWin.slice(0, 3).map((t) => t.team).join(", "));

  const wins = c.teams.reduce((a, t) => a + t.p_win, 0);
  check(Math.abs(wins - 1) < 5e-4, `${c.competition}: exactly one winner — P sums to ${wins.toFixed(4)}`);
  // A round's reach column must sum to the size of the round. The sizes are not asserted from a
  // hardcoded list: each round is half the one before it, and the LAST round is the final, which
  // has two teams in it. Anything else means teams are being counted into the wrong round.
  const sums = c.rounds.map((r) => c.teams.reduce((a, t) => a + t["p_" + r.toLowerCase()], 0));
  const fin = sums[sums.length - 1];
  check(Math.abs(fin - 2) < 2e-3, `${c.competition}: the final has 2 teams in it (${fin.toFixed(3)})`);
  for (let i = c.rounds.length - 1; i > 0; i--) {
    const here = sums[i], before = sums[i - 1];
    // a preliminary round is NOT double the round it feeds -- it is a side door into it
    if (/^PR/.test(c.rounds[i - 1])) continue;
    check(Math.abs(before - 2 * here) < 3e-3,
          `${c.competition}: ${c.rounds[i - 1]} is twice ${c.rounds[i]}`
          + ` (${before.toFixed(2)} vs 2x${here.toFixed(2)})`);
  }
  // every probability is a probability, and reaching a later round is never more likely
  const bad = c.teams.filter((t) => c.rounds.some((r) => {
    const v = t["p_" + r.toLowerCase()];
    return !(v >= 0 && v <= 1);
  }) || t.p_win < 0 || t.p_win > 1);
  check(!bad.length, `${c.competition}: every cell is a probability`, `${bad.length} out of range`);
  // and they must survive the trim, since everything removed contributes zero to both
  const shownWins = shown.teams.reduce((a, t) => a + t.p_win, 0);
  check(Math.abs(shownWins - 1) < 5e-4,
        `${c.competition}: the shown field still holds all the win probability`
        + ` (${shownWins.toFixed(4)})`);
  for (const r of shown.rounds) {
    const all = c.teams.reduce((a, t) => a + t["p_" + r.toLowerCase()], 0);
    const vis = shown.teams.reduce((a, t) => a + t["p_" + r.toLowerCase()], 0);
    check(Math.abs(all - vis) < 5e-4, `${c.competition}: ${r} column intact after the trim`,
          `${all.toFixed(3)} before, ${vis.toFixed(3)} after`);
  }

  const notMono = c.teams.filter((t) => {
    const seq = c.rounds.filter((r) => !/^PR/.test(r)).map((r) => t["p_" + r.toLowerCase()]);
    return seq.some((v, i) => i > 0 && v > seq[i - 1] + 1e-9) || t.p_win > seq[seq.length - 1] + 1e-9;
  });
  check(!notMono.length, `${c.competition}: reaching a later round is never more likely`,
        notMono.slice(0, 3).map((t) => t.team).join(", "));
}
// The legend names the column that answers "did they get through the next tie". Pointing it at a
// preliminary round -- which every side playing one is already in, at p=1 -- sends the reader to a
// column of 100%s for the question they actually asked.
for (const c of CUPS) {
  const {rounds, teams} = X.trimCup(c);
  const d = X.decidedBy(rounds, teams);
  const inPlay = teams.some((t) => t["p_" + d.toLowerCase()] > 0 && t["p_" + d.toLowerCase()] < 1);
  check(inPlay, `${c.competition}: the legend points at ${d}, a round genuinely in the balance`,
        `${d} is settled for every team shown`);
  // ...and it is the round the ties being played now DECIDE: every column before it is certain
  // for the sides certainly playing now. A preliminary can be that round -- the FA Cup's second
  // round is, ahead of the third-round entrants -- but never one those sides are already in.
  const first = "p_" + rounds[0].toLowerCase();
  const sure = teams.filter((t) => t[first] >= 0.9999);
  const before = rounds.slice(0, rounds.indexOf(d));
  check(!sure.length || before.every((r) => sure.every((t) => t["p_" + r.toLowerCase()] >= 0.9999)),
        `${c.competition}: every round before ${d} is certain for the sides playing now`,
        `${before.join(" ")} is not`);
}

// A cup whose pairings are all still to be drawn must say so, and one that is fully bracketed
// must not claim a draw it does not make.
for (const c of CUPS) {
  const markup = X.cup(c);
  check(markup.includes(c.drawn_from ? "drawn afresh in every" : "already known"),
        `${c.competition}: legend matches drawn_from=${c.drawn_from}`);
}

// ---------------------------------------------------------------- which tabs offer views
// A dropdown over a view that cannot render is worse than no dropdown: it looks like a choice.
// Visualisations reads the ratings, which a snapshot carries from version 5.
const hasViz = Boolean(RESULT.ratings);
// The Stats hub reads match stats, from version 9.
const statsOf = (B) => B.teams.some((t) => t.real && t.real.n_stats);
for (const L of RESULT.leagues) {
  const want = X.VIEWS.filter(([k]) => (k !== "viz" || hasViz) && (k !== "stats" || statsOf(L) || X.hasPlayerData(L.competition))
);
  check(X.viewsFor(L.competition).map(([k]) => k).join() === want.map(([k]) => k).join(),
        `${L.competition}: all ${want.length} views (${want.map(([, t]) => t).join(", ")})`);
}
for (const U of RESULT.uefa) {
  const got = X.viewsFor(U.competition).map(([k]) => k);
  const want = X.UEFA_VIEWS.map(([k]) => k).filter((k) => !((k === "phase" || k === "fx") && !U.rounds)
    && !(k === "points" && !U.teams.some((t) => t.pts)) && !(k === "viz" && !hasViz)
    && !(k === "stats" && !statsOf(U) && !X.hasPlayerData(U.competition)));
  check(got.join() === want.join(), `${U.competition}: views ${got.join(", ")}`,
        `want ${want.join(", ")}`);
}
// ---------------------------------------------------------------- UEFA league-phase zones
// Every side finishes somewhere, so top 8 / 9-24 / out partition it; and exactly eight sides are
// top eight in every world, sixteen in the play-off and the rest out, so the columns sum to that.
for (const U of RESULT.uefa) {
  const n = U.teams.length;
  if (U.teams.some((t) => t.p_mid == null)) {
    console.log(`  skip    ${U.competition}: zone checks (snapshot predates p_mid)`);
    continue;
  }
  const part = U.teams.filter((t) => Math.abs(t.p_top8 + t.p_mid + t.p_out - 1) > 2e-4);
  check(!part.length, `${U.competition}: top 8 + play-off + out = 100% for every side`,
        part.slice(0, 3).map((t) => t.team).join(", "));
  const sum = (k) => U.teams.reduce((a, t) => a + t[k], 0);
  check(Math.abs(sum("p_top8") - 8) < 3e-3 && Math.abs(sum("p_mid") - 16) < 3e-3
        && Math.abs(sum("p_out") - (n - 24)) < 3e-3,
        `${U.competition}: the zones hold 8 / 16 / ${n - 24} sides`
        + ` (${sum("p_top8").toFixed(3)} / ${sum("p_mid").toFixed(3)} / ${sum("p_out").toFixed(3)})`);
  const offPts = U.teams.filter((t) => t.pts
    && Math.abs(t.pts.dist.reduce((a, b) => a + b, 0) - 1) > 3e-3);
  check(U.teams.some((t) => t.pts) && !offPts.length,
        `${U.competition}: every side's league-phase points distribution sums to 1`,
        `${offPts.length} off`);
  // the Position and Points views render square tables: the last header row against every body row
  for (const [what, draw] of [["position", () => X.drawDist(U, "position")],
                              ["points", () => X.drawPhasePoints(U)]]) {
    delete els.cview;
    draw();
    const markup = mk("cview").innerHTML;
    const head = markup.slice(0, markup.indexOf("</thead>")).split("<tr>").pop();
    const heads = (head.match(/<th\b/g) || []).length;
    const body = markup.slice(markup.indexOf("<tbody>")).split("<tr>").slice(1);
    const widths = [...new Set(body.map((r) => (r.match(/<td\b/g) || []).length))];
    check(body.length === n && widths.length === 1 && widths[0] === heads,
          `${U.competition} ${what}: ${n} rows, ${heads} headers == ${widths.join("/")} cells`);
  }
}
for (const c of RESULT.cups || []) {
  const want = (RESULT.version || 1) >= 4 ? X.CUP_VIEWS.length : 0;
  check(X.viewsFor(c.competition).length === want,
        `${c.competition}: ${want ? "Overview and Knockout paths" : "Overview only, no dropdown"}`);
}

// ---------------------------------------------------------------- Position and Points, exactly and at least
// Read off the rendered tables, by heading. Every place is filled once a world, so down a Position
// column the sides sum to one side -- and "at least k-th" to k sides; at a zone's last place, at
// least is the zone's own chance (the Overview's UCL, 1 − REL, top 8, 1 − out). "At least so many
// points" is recomputed here from the payload's distribution, under the label the column shows;
// and for a league phase, whose columns are every total, E[points] = Σ P(points ≥ v), so the at-
// least cells of a row sum to its XPTS. Tolerances are the one-decimal display, cell by cell.
{
  const parse = (markup) => {
    const head = markup.slice(0, markup.indexOf("</thead>")).split("<tr>").pop();
    const heads = [...head.matchAll(/<th\b[^>]*>([\s\S]*?)<\/th>/g)].map((m) => m[1].replace(/<[^>]*>/g, "").trim());
    const body = markup.slice(markup.indexOf("<tbody>"), markup.indexOf("</tbody>")).split("<tr>").slice(1)
      .map((r) => [...r.matchAll(/<td\b[^>]*>([\s\S]*?)<\/td>/g)].map((m) => m[1].replace(/<[^>]*>/g, "").trim()));
    return {heads, body};
  };
  const cell = (s) => s === "·" || s === "" ? 0 : parseFloat(s);
  let tables = 0, cells = 0;
  const off = [];
  for (const B of [...RESULT.leagues, ...RESULT.uefa]) {
    const phase = RESULT.uefa.includes(B);
    const n = B.teams.length, zones = X.zonesOf(B);
    for (const mode of ["exact", "atleast"]) {
      X.DISTMODE = mode;
      for (const which of ["position", "points"]) {
        if (which === "points" && !B.teams.some((t) => t.pts && t.pts.dist)) continue;
        delete els.cview;
        X.drawDist(B, which);
        const {heads, body} = parse(mk("cview").innerHTML);
        const tag = `${B.competition} ${which} ${mode}`;
        tables++;
        const first = heads.indexOf("") + 1;               // the spacer, then the distribution
        const labels = heads.slice(first);
        if (first < 1 || !labels.length || body.some((r) => r.length !== heads.length)) { off.push(`${tag} not square`); continue; }
        const rows = body.map((r) => ({team: r[0], v: r.slice(first).map(cell), r}));
        const byTeam = Object.fromEntries(B.teams.map((t) => [t.team, t]));
        cells += rows.length * labels.length;
        const tol = labels.length * 0.05 + 1e-9;
        if (rows.length !== (which === "points" ? B.teams.filter((t) => t.pts).length : n)) off.push(`${tag} ${rows.length} rows`);
        for (const {team, v} of rows) {
          if (mode === "exact" && Math.abs(v.reduce((a, b) => a + b, 0) - 100) > tol) off.push(`${tag} ${team} row sum`);
          if (mode === "atleast" && (v.some((x, k) => k && x < v[k - 1] - 1e-9) || Math.abs(v[v.length - 1] - 100) > 0.1)) {
            off.push(`${tag} ${team} does not climb to 100`);
          }
        }
        if (which === "position") {
          labels.forEach((l, k) => {
            const sum = rows.reduce((a, r) => a + r.v[k], 0);
            const want = mode === "exact" ? 100 : 100 * (k + 1);
            if (+l !== k + 1 || Math.abs(sum - want) > n * 0.05 + 1e-6) off.push(`${tag} place ${l}: ${sum.toFixed(1)} not ${want}`);
          });
          if (mode === "atleast") {
            const edges = phase ? [[8, (t) => t.p_top8], [24, (t) => 1 - t.p_out]]
              : B.qualification?.mode === "per_world" ? [[1, (t) => t.p_win], [n - (B.relegated ?? 3), (t) => 1 - t.p_releg]]
              : [[B.ucl_spots ?? 4, (t) => t.p_ucl ?? t.p_top4], [n - (B.relegated ?? 3), (t) => 1 - t.p_releg]];
            for (const [k, p] of edges) {
              for (const {team, v} of rows) {
                const want = p(byTeam[team]);
                // the shown cell's half-unit, the k summed four-place probabilities, the payload's own
                if (want != null && Math.abs(v[k - 1] - 100 * want) > 0.05 + k * 0.005 + 0.005 + 1e-9) {
                  off.push(`${tag} ${team} at least ${k}: ${v[k - 1]} not ${(100 * want).toFixed(2)}`);
                }
              }
            }
          }
          // the place now: each place once, and never above a side with more points
          const iP = heads.indexOf("POS"), iPts = heads.indexOf("PTS");
          if (iP >= 0) {
            const pos = rows.map(({r}) => +r[iP]).sort((a, b) => a - b);
            const perm = pos.every((p, k) => p === k + 1);
            const ordered = rows.every(({r: a}) => rows.every(({r: b}) => !(+a[iPts] > +b[iPts] && +a[iP] > +b[iP])));
            if (!perm || !ordered) off.push(`${tag} POS ${perm ? "out of points order" : "not each place once"}`);
          }
        } else if (mode === "atleast") {
          // the label is the column's lowest total; its cell is the payload's own tail there
          const los = labels.map((l) => parseInt(l, 10));
          for (const {team, v} of rows) {
            const P = byTeam[team].pts, tot = P.dist.reduce((a, b) => a + b, 0) || 1;
            los.forEach((lo, k) => {
              const tail = P.dist.reduce((a, p, i) => a + (i + P.offset >= lo ? p : 0), 0) / tot;
              if (Math.abs(v[k] - 100 * tail) > 0.05 + 1e-6) off.push(`${tag} ${team} ${lo}+: ${v[k]} not ${(100 * tail).toFixed(2)}`);
            });
            if (phase) {
              // E[X] = Σ_{v ≥ 1} P(X ≥ v); totals below the last shown column are certain
              const low = Math.min(...los);
              const tailSum = los.reduce((a, lo, k) => a + (lo >= 1 ? v[k] / 100 : 0), 0) + Math.max(0, low - 1);
              const xp = +rows.find((r) => r.team === team).r[heads.indexOf("XPTS")];
              if (Math.abs(tailSum - xp) > 0.05 + los.length * 0.0005 + 0.01) off.push(`${tag} ${team} tails ${tailSum.toFixed(2)} not XPTS ${xp}`);
            }
          }
        }
      }
    }
  }
  X.DISTMODE = "exact";
  check(tables > 0 && cells > 0 && !off.length,
        `position and points: ${tables} tables, exactly and at least (${cells} cells) — places filled once,`
        + ` zone edges are the zone's chance, tails are the payload's, a league phase's tails sum to XPTS`,
        `${off.length} off, e.g. ${off.slice(0, 4).join("; ")}`);
}

// ---------------------------------------------------------------- tab order
// The page's tab order IS this list, so it is asserted rather than eyeballed: every competition
// the data carries appears exactly once, grouped by country, league before that country's cups.
{
  const present = X.presentComps();
  const groups = X.tabGroups(present);
  const flat = groups.flatMap(([, cs]) => cs);
  check(flat.length === present.size && new Set(flat).size === flat.length,
        `every competition gets exactly one tab (${flat.length} of ${present.size})`,
        `tabs ${flat.length}, present ${present.size}`);
  check(!groups.some(([c]) => c === "Other"),
        "no competition falls through to \"Other\"",
        (groups.find(([c]) => c === "Other") || [, []])[1].join(", "));
  const want = X.COMP_ORDER.filter((c) => present.has(c));
  check(flat.join("|") === want.join("|"), "tabs follow GROUPS order",
        `got ${flat.join(", ")}`);
  console.log("  ---   " + groups.map(([c, cs]) => `${c}: ${cs.length}`).join(" · "));
}

// ---------------------------------------------------------------- the away mirror
// Home-oriented storage means an away row must flip every key -- the result, both margin slices
// and the clean sheet. Unflipped, an away row inverts and still looks entirely plausible. Tested
// on every fixture that IS both sides' next one: an index entry pointing at an earlier fixture
// would be comparing two different matches.
{
  const both = MATCHES.fixtures.filter((f) => f.ladder
    && NEXT[f.competition]?.[f.home]?.kickoff === f.kickoff
    && NEXT[f.competition]?.[f.away]?.kickoff === f.kickoff);
  const off = both.filter((f) => {
    const h = NEXT[f.competition][f.home], a = NEXT[f.competition][f.away], L = f.ladder;
    return !(h.w2 === L.h2 && h.w === L.h1 && h.d === L.d && h.l === L.a1 && h.l2 === L.a2
             && h.cs === f.cs_h
             && a.w2 === L.a2 && a.w === L.a1 && a.d === L.d && a.l === L.h1 && a.l2 === L.h2
             && a.cs === f.cs_a);
  });
  check(both.length > 0 && !off.length,
        `away rows mirror every key, home rows are left alone (${both.length} fixtures)`,
        off.length ? `${off.length} wrong, e.g. ${off[0].home} v ${off[0].away}` : "nothing to test");
}

// ---------------------------------------------------------------- the next-fixture block, as read
// Off the RENDERED tables, under the headings a reader sees: W + D + L is 100%, W2+ and L2+ are
// slices of W and L, and a clean sheet needs a W or a D. A cell under the wrong heading breaks at
// least one of these, and so does a row showing the OPPONENT's clean sheet -- on a lopsided
// fixture the favourite's CS is more than the underdog's W + D. Tolerances are for the one-decimal
// display: three cells each rounded by up to 0.05pp.
{
  const want = X.NEXT_COLS.map(([, t]) => t);
  const tables = [...RESULT.leagues.map((l) => [l.competition, X.league(l)]),
                  ...RESULT.uefa.map((u) => [u.competition, X.uefa(u)]),
                  ...CUPS.map((c) => [c.competition, X.cup(c)])];
  let shown = 0;
  for (const [comp, markup] of tables) {
    const rows = markup.split("<tr>").slice(1);
    const heads = [...rows[0].matchAll(/<th\b[^>]*>([\s\S]*?)<\/th>/g)].map((m) => m[1].replace(/<[^>]*>/g, "").trim());
    check(heads.slice(-want.length).join(" ") === want.join(" "),
          `${comp}: the last ${want.length} columns are ${want.join(" ")}`,
          `got ${heads.slice(-want.length).join(" ")}`);
    const at = heads.length - want.length;
    const bad = [], missing = [];
    let n = 0, noCleanSheet = 0;
    for (const r of rows.slice(1)) {
      const tds = [...r.matchAll(/<td\b[^>]*>([\s\S]*?)<\/td>/g)].map((m) => m[1].trim());
      const v = tds.slice(at).map((s) => s.endsWith("%") ? parseFloat(s) : null);
      const team = (r.match(/<td\b[^>]*data-team="([^"]*)"/) || [, ""])[1]
        .replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&amp;/g, "&");
      const source = (NEXT[comp] || {})[team];
      if (!source) continue;                                  // no fixture, or not drawn
      const available = X.NEXT_COLS.map(([key]) => source[key] != null);
      if (source.cs == null) noCleanSheet++;
      if (v.some((x, i) => available[i] && x == null)) { missing.push(team); continue; }
      // by heading, not by position, so the identities are about what each column CLAIMS to be
      const c = Object.fromEntries(want.map((t, i) => [t, v[i]]));
      n++;
      if (Math.abs(c.W + c.D + c.L - 100) > 0.2 || c["W2+"] > c.W || c["L2+"] > c.L
          || (c.CS != null && c.CS > c.W + c.D + 0.2)) {
        bad.push(`${team} ${v.join("/")}`);
      }
    }
    shown += n;
    if (noCleanSheet) console.log(`  skip    ${comp}: CS identity on ${noCleanSheet} older next fixtures without clean-sheet fields (W/D/L still checked)`);
    check(!missing.length, `${comp}: ${n} fixture rows fill every probability cell their snapshot carries`,
          `${missing.length} with a gap, e.g. ${missing.slice(0, 3).join(", ")}`);
    check(!bad.length, `${comp}: W+D+L = 100%, W2+ <= W, L2+ <= L, CS <= W+D (${n} rows)`,
          `${bad.length} rows off, e.g. ${bad.slice(0, 2).join("; ")}`);
  }
  check(shown > 0, `the next-fixture identities were tested on ${shown} rendered rows`);
}

// ---------------------------------------------------------------- European places, run-ins
// In every world exactly ucl / uel / uecl sides finish in each band of places, so the columns
// sum to those counts; and each run-in is at most five fixtures, in date order, banded 1..5.
for (const L of RESULT.leagues) {
  if (L.uel_spots == null) continue;
  const sum = (k) => L.teams.reduce((a, t) => a + (t[k] || 0), 0);
  const actual = L.qualification?.mode === "per_world", counts = actual ? L.qualification.mean : {ucl: L.ucl_spots, uel: L.uel_spots, uecl: L.uecl_spots};
  check(["ucl", "uel", "uecl"].every((key) => Number.isFinite(counts?.[key])
          && Math.abs(sum("p_" + key) - counts[key]) <= L.teams.length * .00005 + .00005 + 1e-9),
        `${L.competition}: the UCL / UEL / UECL columns hold ${counts?.ucl} / ${counts?.uel} /`
        + ` ${counts?.uecl} sides (${actual ? "per-world top-flight entry means, including qualifying" : "places from " + L.places_from})`);
}
for (const B of [...RESULT.leagues, ...RESULT.uefa]) {
  if (!B.teams.some((t) => t.next5)) continue;
  const bad = B.teams.filter((t) => (t.next5 || []).length > 5
    || (t.next5 || []).some(([, , , b], i, a) => !(b >= 1 && b <= 5) || (i && a[i - 1][4] > a[i][4])));
  const n = B.teams.reduce((a, t) => a + (t.next5 || []).length, 0);
  check(n > 0 && !bad.length, `${B.competition}: ${n} run-in fixtures, five a side at most,`
        + ` in date order and banded 1-5`, bad.slice(0, 3).map((t) => t.team).join(", "));
}

// W/D/L partitions the outcome, at the stored precision.
for (const L of RESULT.leagues) {
  const bad = L.teams.map((t) => NEXT[L.competition]?.[t.team])
    .filter((n) => n && Math.abs(n.w + n.d + n.l - 1) >= 3e-4);
  check(!bad.length, `${L.competition}: W+D+L sums to 1 for every team`,
        `${bad.length} rows off`);
}

// ---------------------------------------------------------------- the gameweek view
// A table of whole numbers built from means is only trustworthy if it is EXACT where the answer
// is known: going into the gameweek after the last round played in full, it must be the real
// table, recomputed here from the results themselves. Beyond that every row must be a record a
// season could produce and the nearest one to its means, the table must be in the order it
// claims (PTS, then the exact XPTS), and the payload's means must
// balance the way every world's do: one side's win is another's loss, one side's goals another's
// conceded.
const rowsOf = (markup) => markup.split("<tr>").slice(1).map((r) =>
  [...r.matchAll(/<t([dh])\b[^>]*>([\s\S]*?)<\/t\1>/g)].map((m) => m[2]));
const clean = (s) => s.replace(/<span[^>]*>\d+<\/span>/, "").replace(/<[^>]*>/g, "").trim();
// columns by heading, not by position: the rating columns (version 5) sit between XPTS and the
// fixture, and a positional read of an older layout would quietly compare the wrong cells.
// indexOf finds the table's W/D/L, which come before the fixture block's.
const colsOf = (rows) => {
  const h = rows[1].map(clean);
  const at = (name) => { const i = h.indexOf(name); if (i < 0) throw new Error(`no ${name} column`); return i; };
  return {pl: at("PL"), w: at("W"), d: at("D"), l: at("L"), goals: at("+/−"), gd: at("GD"),
          pts: at("PTS"), xpts: at("XPTS"), opp: h.indexOf("Opponent"), elo: h.indexOf("ELO"),
          xfa: h.indexOf("x+/x−"), xgd: h.indexOf("xGD"), xgp: h.indexOf("xG PTS")};
};
const GWD = gwPath && gwPath !== "-" ? JSON.parse(readFileSync(gwPath, "utf8")) : null;
if (!GWD) {
  console.log("  skip    gameweek checks (no gw.json passed)");
} else {
  for (const [comp, g] of Object.entries({...GWD.leagues, ...(GWD.phases || {})})) {
    const sum = (k, at) => g[k].reduce((a, row) => a + row[at], 0);
    let off = 0;
    for (let at = 0; at <= g.rounds; at++) {
      off = Math.max(off, Math.abs(sum("w", at) - sum("l", at)), Math.abs(sum("gf", at) - sum("ga", at)));
      g.teams.forEach((_, i) => {
        off = Math.max(off, Math.abs(g.w[i][at] + g.d[i][at] + g.l[i][at] - g.pl[i][at]));
      });
    }
    // rounding to two places, over up to twenty sides
    check(off < 0.15, `${comp}: the gameweek means balance (W = L, GF = GA, W+D+L = PL)`,
          `worst ${off.toFixed(3)}`);
    // one champion and `relegated` sides a world, each settled in exactly one round
    if (g.clinch) {
      const L = RESULT.leagues.find((x) => x.competition === comp);
      const t = g.clinch.reduce((a, [, , p]) => a + p, 0);
      const d = (g.down || []).reduce((a, [, , p]) => a + p, 0);
      check(Math.abs(t - 1) < 3e-3 && L && Math.abs(d - L.relegated) < 3e-3,
            `${comp}: the title is settled once a world (${t.toFixed(3)}) and ${L && L.relegated}`
            + ` relegation places too (${d.toFixed(3)})`);
    }

    let full = 0;
    for (let r = 1; r <= g.rounds; r++) {
      const fx = g.fixtures.filter((f) => f.round === r);
      if (fx.length && fx.every((f) => f.result)) full = r; else break;
    }
    const real = Object.fromEntries(g.teams.map((t) => [t, [0, 0, 0, 0, 0, 0]]));
    for (const f of g.fixtures.filter((x) => x.round <= full)) {
      const [h, a] = f.result;
      for (const [t, gf, ga] of [[f.home, h, a], [f.away, a, h]]) {
        const s = real[t];
        s[0] += 1; s[1] += gf > ga; s[2] += gf === ga; s[3] += gf < ga; s[4] += gf; s[5] += ga;
      }
    }
    const pastRows = rowsOf(X.gwTable(g, full + 1, GWD.worlds));
    const C = colsOf(pastRows);
    const past = pastRows.slice(2);
    const wrong = past.filter((c) => {
      const s = real[clean(c[0])];
      const [gf, ga] = clean(c[C.goals]).split("–").map(Number);
      return !s || [+c[C.pl], +c[C.w], +c[C.d], +c[C.l], gf, ga].some((v, k) => v !== s[k]);
    });
    check(full > 0 && past.length === g.teams.length && !wrong.length,
          `${comp}: GW ${full + 1} shows the real table after GW ${full}, round ${full} being the last played in full`,
          `${wrong.length} rows differ, e.g. ${wrong.slice(0, 2).map((c) => clean(c[0])).join(", ")}`);

    // Each gameweek is its own snapshot of the means, so what is asserted is that every row at
    // EVERY gameweek renders its own means faithfully: W/D/L the whole record of PL matches
    // nearest them, PTS = 3W + D, and the table in PTS order, sides level on points in XPTS order.
    // The oracle is the closed form, not intRecord's search: the nearest record with a fixed sum
    // rounds every count down and gives the matches left over to the largest remainders
    // (Hamilton's method). Two consequences are asserted too: no count is a whole match from its
    // mean, and PTS is within 5/3 of a point of XPTS (plus the means' two-decimal rounding).
    // Consecutive gameweeks are not required to chain -- an average of seasons is not a season --
    // so how often they do is reported, not asserted.
    const nearest = (pl, x) => {
      const down = x.map(Math.floor);
      const up = x.map((v, k) => [v - down[k], k]).sort((a, b) => b[0] - a[0])
                  .slice(0, pl - down[0] - down[1] - down[2]).map(([, k]) => k);
      return x.reduce((s, v, k) => s + (down[k] + up.includes(k) - v) ** 2, 0);
    };
    const index = Object.fromEntries(g.teams.map((t, i) => [t, i]));
    let worst = 0, steps = 0, chained = 0;
    const faults = [], last = {};
    for (let gw = 1; gw <= g.rounds + 1; gw++) {
      const at = gw - 1;
      let above = null;
      const gwRows = rowsOf(X.gwTable(g, gw, GWD.worlds));
      const K = colsOf(gwRows);
      for (const c of gwRows.slice(2)) {
        const team = clean(c[0]), i = index[team];
        const [pl, w, d, l, pts] = [+c[K.pl], +c[K.w], +c[K.d], +c[K.l], +clean(c[K.pts])];
        const x = [g.w[i][at], g.d[i][at], g.l[i][at]];
        const xp = 3 * x[0] + x[1];
        const spread = [w, d, l].reduce((s, v, k) => s + (v - x[k]) ** 2, 0);
        const off = Math.abs(pts - xp);
        worst = Math.max(worst, off);
        if (pl !== g.pl[i][at] || w + d + l !== pl || pts !== 3 * w + d
            || spread > nearest(pl, x) + 1e-9 || [w, d, l].some((v, k) => Math.abs(v - x[k]) >= 1)
            || off >= 5 / 3 + 0.05
            || (above && (pts > above.pts || (pts === above.pts && xp > above.xp + 1e-9)))) {
          faults.push(`GW ${gw} ${team}`);
        }
        above = {pts, xp};
        const prev = last[team];
        if (prev && pl === prev.pl + 1 && x.some((v) => !Number.isInteger(v))) {
          steps++;
          chained += [w - prev.w, d - prev.d, l - prev.l].sort().join() === "0,0,1";
        }
        last[team] = {pl, w, d, l};
      }
    }
    check(!faults.length,
          `${comp}: at every gameweek W/D/L is the record nearest the means, PTS follows, in PTS`
          + ` order (worst |PTS − XPTS| ${worst.toFixed(2)}; ${chained} of ${steps} projected`
          + ` steps a single result)`,
          `${faults.length} rows wrong, e.g. ${faults.slice(0, 3).join(", ")}`);

    const x = Math.min(g.rounds, X.defaultGw(g) + 5);
    const rows = rowsOf(X.gwTable(g, x, GWD.worlds));
    const heads = rows[1].length;
    const body = rows.slice(2);
    const P = colsOf(rows);
    const parsed = body.map((c) => {
      const [gf, ga] = clean(c[P.goals]).split("–").map(Number);
      return {team: clean(c[0]), pl: +c[P.pl], w: +c[P.w], d: +c[P.d], l: +c[P.l], gf, ga,
              gd: +clean(c[P.gd]).replace("−", "-"), pts: +clean(c[P.pts]), xpts: +clean(c[P.xpts]),
              opp: clean(c[P.opp])};
    });
    const bad = parsed.filter((r) => r.w + r.d + r.l !== r.pl || r.pts !== 3 * r.w + r.d
                                      || r.gd !== r.gf - r.ga);
    const order = parsed.every((r, i) => i === 0 || r.pts < parsed[i - 1].pts
                               || (r.pts === parsed[i - 1].pts && r.xpts <= parsed[i - 1].xpts));
    const noFixture = parsed.filter((r) => r.opp === "no fixture");
    check(body.every((c) => c.length === heads) && !bad.length && order && !noFixture.length,
          `${comp}: GW ${x} rows are records a season could produce, in PTS order, each with a fixture`,
          `widths ${[...new Set(body.map((c) => c.length))]} vs ${heads}; ${bad.length} inconsistent;`
          + ` order ${order}; ${noFixture.length} without a fixture`);
  }
}

// ---------------------------------------------------------------- history charts
const specs = [["position", X.HIST_POS(RESULT.leagues[0].teams.length), ""],
               ["points", X.HIST_PTS, ""],
               ["title", X.HIST_WIN(true), "%"]];
for (const [name, spec, unit] of specs) {
  // the page's own rule: a trend needs two snapshots, and with one it says so instead
  if ((HISTORY.dates || []).length < 2) { console.log(`  skip    ${name} chart (one snapshot: no trend to draw)`); continue; }
  delete els.hview;
  const target = mk("hview");
  await X.drawHistory(RESULT.leagues[0].competition, spec);
  const out = target.innerHTML;
  const teams = Object.keys(HISTORY.competitions[RESULT.leagues[0].competition] || {}).length;
  // the shared line chart: a faint line for each side not lit (its hit target carries data-hl),
  // and the lit ones, one to four, whose chips are pressed
  const faint = (out.match(/<path [^>]*data-hl=/g) || []).length;
  const lit = (out.match(/<button data-hl="[^"]*" aria-pressed="true"/g) || []).length;
  const chips = (out.match(/<button data-hl=/g) || []).length;
  check(lit >= 1 && lit <= 4 && faint + lit === teams && chips === teams,
        `${name} chart: one line per team (${teams}: ${faint} faint, ${lit} lit, ${chips} chips)`);
  const ticks = [...out.matchAll(/text-anchor="end">([^<]*)</g)].map((m) => m[1]);
  check(ticks.length > 0 && ticks.every((t) => unit ? t.endsWith(unit) : !t.endsWith("%")),
        `${name} chart: axis labelled "${unit || "bare"}" — ${ticks.join(" ")}`);
}

// ---------------------------------------------------------------- knockout paths
// The path is two counts per opponent -- met, and went through -- so its identity is exact: over
// a round's opponents, P(meet) x P(through | met) is P(going through that round), which the
// projection carries independently as the next round's reach (less P(top 8) for the play-off,
// which the top eight skip). Then every rendered path renders square, with a row per opponent.
const PATHSD = pathsPath && pathsPath !== "-" ? JSON.parse(readFileSync(pathsPath, "utf8")) : null;
if (!PATHSD) {
  console.log("  skip    knockout path checks (no paths.json passed)");
} else {
  for (const U of RESULT.uefa) {
    const P = PATHSD.competitions[U.competition];
    check(Boolean(P), `${U.competition}: has knockout paths`);
    if (!P) continue;
    let worst = 0, at = "", n = 0, tables = 0, bad = [];
    for (const t of U.teams) {
      const odds = X.stageOdds(t);
      for (const [stage, blk] of Object.entries(P.teams[t.team] || {})) {
        const [reach, s] = X.roundOdds(blk);
        const off = Math.max(Math.abs(s - odds[stage][1]), Math.abs(reach - odds[stage][0]));
        n++;
        if (off > worst) { worst = off; at = `${t.team} ${stage}`; }
      }
      const spec = X.pathSpec(U, "uefa", t);
      const markup = X.pathsHtml(P, t.team, spec.stages, spec.funnel, spec.note);
      for (const tbl of markup.split("<table").slice(1)) {
        const head = tbl.slice(0, tbl.indexOf("</thead>"));
        const heads = (head.match(/<th\b/g) || []).length;
        const rows = tbl.slice(tbl.indexOf("<tbody>"), tbl.indexOf("</tbody>")).split("<tr>").slice(1);
        tables++;
        if (!rows.length || rows.some((r) => (r.match(/<td\b/g) || []).length !== heads)) {
          bad.push(t.team);
        }
      }
    }
    // four-place rounding of each P(meet) and three of P(through), over up to seven rows
    check(n > 0 && worst < 2e-3, `${U.competition}: over each round's opponents, meet sums to the`
          + ` chance of playing it and meet x through to going through (${n} side-rounds,`
          + ` worst ${worst.toFixed(5)} ${at})`);
    check(tables > 0 && !bad.length, `${U.competition}: ${tables} rendered path tables are square`,
          `${bad.length} not, e.g. ${bad.slice(0, 3).join(", ")}`);
  }
  // A cup's path cannot exceed its reach ladder: a side plays a round at most as often as it is in
  // it (less any bye), and goes through it at most as often as it reaches the next round.
  for (const c of CUPS) {
    const P = (PATHSD.cups || {})[c.competition];
    if (!P) { console.log(`  skip    ${c.competition}: no cup paths in this snapshot`); continue; }
    const rounds = c.rounds;
    let n = 0, over = [];
    for (const t of c.teams) {
      for (const [r, blk] of Object.entries(P.teams[t.team] || {})) {
        const [reach, thr] = X.roundOdds(blk);
        const i = rounds.indexOf(r);
        const next = i + 1 < rounds.length ? t["p_" + rounds[i + 1].toLowerCase()] : t.p_win;
        n++;
        if (reach > t["p_" + r.toLowerCase()] + 2e-3 || thr > next + 2e-3) over.push(`${t.team} ${r}`);
      }
    }
    check(n > 0 && !over.length, `${c.competition}: ${n} path rounds sit inside the reach ladder`,
          `${over.length} over, e.g. ${over.slice(0, 3).join(", ")}`);
  }
}

// ---------------------------------------------------------------- ratings and visualisations
// Version 5. The identities: one row per side, the scale's own (the average side makes what it
// concedes), the worlds' first projected round agreeing with today where nothing can have moved
// it, and every chart drawing exactly one mark per side -- with badges and without.
if (!RESULT.ratings) {
  console.log("  skip    ratings checks (a snapshot before version 5)");
} else {
  const RT = RESULT.ratings;
  const names = RT.teams.map((r) => r.team);
  const want = new Set([...RESULT.leagues, ...RESULT.uefa].flatMap((b) => b.teams.map((t) => t.team)));
  const missing = [...want].filter((t) => !names.includes(t));
  check(names.length === new Set(names).size && !missing.length,
        `ratings: every league and league-phase side rated exactly once (${names.length})`,
        `${missing.length} missing, e.g. ${missing.slice(0, 3).join(", ")}`);
  const lg = RT.teams.filter((r) => r.league);
  const gm = (k) => Math.exp(lg.reduce((a, r) => a + Math.log(r[k]), 0) / lg.length);
  check(lg.length >= 90 && Math.abs(gm("att") / gm("def") - 1) < 2e-3,
        `ratings: over the ${lg.length} league sides the average side makes what it concedes`
        + ` (ATT ${gm("att").toFixed(3)}, DEF ${gm("def").toFixed(3)})`);
  const leagueOf = Object.fromEntries(RESULT.leagues.flatMap((L) => L.teams.map((t) => [t.team, L.competition])));
  const wrongLeague = RT.teams.filter((r) => leagueOf[r.team] && r.league !== leagueOf[r.team]);
  check(!wrongLeague.length, `ratings: each side's league is the table it is in`,
        wrongLeague.slice(0, 3).map((r) => r.team).join(", "));

  // read off the rendered tab, for every window: square, in Elo order, and each change cell
  // exactly now minus the window's start (Elo to the whole point, NET to two places)
  const wins = RT.windows || [];
  check(!RT.windows || (wins.length >= 1 && wins.every((w) => w.date < RT.as_of)),
        `ratings: ${wins.length} change windows, each starting before the data cutoff`
        + ` (${wins.map((w) => `${w.key} ${w.date}`).join(", ")})`);
  for (const w of wins.length ? wins : [null]) {
    if (w) X.DWIN = w.key;
    delete els.view;
    X.drawRatings();
    const rmark = mk("view").innerHTML;
    const rrows = rmark.split("<tbody>")[1].split("</tbody>")[0].split("<tr>").slice(1);
    const hcells = [...rmark.split("<thead>")[1].split("</thead>")[0].matchAll(/<th\b[^>]*>([\s\S]*?)<\/th>/g)]
      .map((m) => m[1].replace(/<[^>]*>/g, "").replace(/▼|▲/g, "").trim());
    const cells = rrows.map((r) => [...r.matchAll(/<td\b[^>]*>([\s\S]*?)<\/td>/g)].map((m) => m[1]));
    const txt = (c) => c.replace(/<span[^>]*>\d+<\/span>/, "").replace(/<[^>]*>/g, "").trim();
    const num = (c) => parseFloat(txt(c).replace("−", "-").replace("▲", "").replace("▼", "-"));
    const iE = hcells.indexOf("ELO"), iN = hcells.indexOf("NET");
    const ordered = cells.every((c, k) => k === 0 || num(c[iE]) <= num(cells[k - 1][iE]));
    let off = 0, n = 0;
    if (w) {
      cells.forEach((c) => {
        const r = X.ratingIdx()[txt(c[0])], pst = r && r.past && r.past[w.key];
        if (!pst) return;
        n++;
        // the shown change is the exact one to the precision shown: half a point, half a cent
        if (Math.abs(num(c[iE + 1]) - (r.elo - pst[0])) > 0.5 + 1e-9
            || Math.abs(num(c[iN + 1]) - (r.att - r.def - (pst[1] - pst[2]))) > 0.005 + 1e-9) off++;
      });
    }
    check(rrows.length === RT.teams.length && cells.every((c) => c.length === hcells.length) && ordered
          && (!w || (hcells[iE + 1] === hcells[iN + 1] && hcells[iE + 1].startsWith("Δ") && n > 0 && !off)),
          `ratings tab${w ? ` over ${w.label}` : ""}: ${rrows.length} rows square at ${hcells.length} columns,`
          + ` in Elo order${w ? `; ${n} change cells are now minus then` : ""}`,
          `ordered ${ordered}, ${off} change cells off`);
  }
  X.DWIN = "1w";

  // A competition's own scale (version 7): read against its own average side, its sides balance
  // -- the geometric means of ATT and DEF agree -- at every real round of its Gameweek view, and
  // on the Ratings tab filtered to it, read back off the rendered cells (two decimals there)
  if (RT.rel) {
    let blocks = 0, worstG = 0, at0 = "";
    for (const [comp, g] of Object.entries({...(GWD || {}).leagues, ...((GWD || {}).phases || {})})) {
      if (g.rating_scale !== "competition") continue;
      blocks++;
      g.rating_real.forEach((real, at) => {
        if (!real) return;
        const gmA = Math.exp(g.att.reduce((a, r) => a + Math.log(r[at]), 0) / g.att.length);
        const gmD = Math.exp(g.def.reduce((a, r) => a + Math.log(r[at]), 0) / g.def.length);
        if (Math.abs(gmA / gmD - 1) > worstG) { worstG = Math.abs(gmA / gmD - 1); at0 = `${comp} ${at}`; }
      });
    }
    check(!GWD || (blocks > 0 && worstG < 3e-3), `own scale: ${blocks} gameweek blocks balance at every`
          + ` real round (worst |ATT/DEF − 1| ${worstG.toExponential(1)} ${at0})`);
    const comps = Object.keys(RT.rel).filter((comp) => RT.teams.some((r) => r.league === comp || r.uefa === comp));
    if (Object.keys(RT.rel).length > comps.length) console.log(`  skip    Ratings filter balance for ${Object.keys(RT.rel).length - comps.length} cup references (used by match cards; cups are not Ratings filters)`);
    let worstR = 0, atR = "", n = 0;
    for (const comp of comps) {
      X.RATSEL = comp;
      delete els.view;
      X.drawRatings();
      const rmark = mk("view").innerHTML;
      const hc = [...rmark.split("<thead>")[1].split("</thead>")[0].matchAll(/<th\b[^>]*>([\s\S]*?)<\/th>/g)]
        .map((m) => m[1].replace(/<[^>]*>/g, "").replace(/▼|▲/g, "").trim());
      const iA = hc.indexOf("ATT"), iD = hc.indexOf("DEF");
      const rows = rmark.split("<tbody>")[1].split("</tbody>")[0].split("<tr>").slice(1)
        .map((r) => [...r.matchAll(/<td\b[^>]*>([\s\S]*?)<\/td>/g)].map((m) => parseFloat(m[1])));
      const gm = (i) => Math.exp(rows.reduce((a, c) => a + Math.log(c[i]), 0) / rows.length);
      n += rows.length;
      if (Math.abs(gm(iA) / gm(iD) - 1) > worstR) { worstR = Math.abs(gm(iA) / gm(iD) - 1); atR = comp; }
    }
    X.RATSEL = "all";
    check(comps.length >= 8 && worstR < 5e-3, `own scale: the Ratings tab filtered to each of ${comps.length}`
          + ` competitions balances (${n} rows, worst |ATT/DEF − 1| ${worstR.toExponential(1)} ${atR})`);
  } else {
    console.log("  skip    own-scale checks (a snapshot before version 7)");
  }

  if (GWD) {
    let exact = 0, off = [], blocks = 0, lengthBad = [];
    for (const [comp, g] of Object.entries({...GWD.leagues, ...(GWD.phases || {})})) {
      if (!Array.isArray(g.elo)) continue;
      blocks++;
      if (g.rating_days.length !== g.rounds + 1 || g.elo.some((row) => row.length !== g.rounds + 1)) lengthBad.push(comp);
      const first = g.rating_real.indexOf(false);
      if (first < 0) continue;
      g.teams.forEach((team, i) => {
        // no spread across the worlds means every world handed the side the same Elo: today's
        if (g.elo_sd[i][first] === 0) {
          const r = X.ratingIdx()[team];
          if (r && Math.abs(g.elo[i][first] - r.elo) < 0.11) exact++; else off.push(`${comp} ${team}`);
        }
      });
    }
    check(blocks > 0 && !lengthBad.length, `gameweek ratings: ${blocks} blocks carry one rating per round and the end`,
          lengthBad.join(", "));
    check(exact > 0 && !off.length, `gameweek ratings: ${exact} sides no world moves before the next round`
          + ` carry exactly today's Elo into it`, `${off.length} differ, e.g. ${off.slice(0, 3).join(", ")}`);
    // a rendered gameweek with ratings: the columns are there and hold the payload's numbers
    const L0 = RESULT.leagues[0], g0 = GWD.leagues[L0.competition];
    if (g0 && Array.isArray(g0.elo)) {
      const x = Math.min(g0.rounds, X.defaultGw(g0) + 3);
      const rows = rowsOf(X.gwTable(g0, x, GWD.worlds));
      const C = colsOf(rows);
      const hasX = Array.isArray(g0.xgf);
      const bad = rows.slice(2).filter((c) => {
        const i = g0.teams.indexOf(clean(c[0]));
        // shown to the precision shown: half a unit, and a hair for 0.955 being 0.95499... in binary
        if (Math.abs(+clean(c[C.elo]) - g0.elo[i][x - 1]) > 0.5 + 1e-9) return true;
        if (!hasX) return false;
        const [f, a] = clean(c[C.xfa]).split("–").map(Number);
        return Math.abs(f - g0.xgf[i][x - 1]) > 0.05 + 1e-9 || Math.abs(a - g0.xga[i][x - 1]) > 0.05 + 1e-9
          || Math.abs(+clean(c[C.xgp]) - g0.xgpts[i][x - 1]) > 0.05 + 1e-9;
      });
      check(C.elo > C.xpts && (!hasX || (C.xfa > C.xpts && C.xgd === C.xfa + 1 && C.xgp === C.xfa + 2)) && !bad.length,
            `${L0.competition}: GW ${x} shows ${hasX ? "x+/x−, xGD, xG PTS and " : ""}ELO after XPTS, matching the payload`,
            `${bad.length} rows differ`);
    }
  }

  const fakeBadges = Object.fromEntries([...want].map((t, i) => [t, `${1000 + i}.png`]));
  for (const B of [RESULT.leagues[0], RESULT.uefa[0]]) {
    const kind = RESULT.leagues.includes(B) ? "league" : "uefa";
    const g = GWD ? ((kind === "league" ? GWD.leagues : GWD.phases) || {})[B.competition] : null;
    for (const [badges, tag] of [[{}, "dots"], [fakeBadges, "badges"]]) {
      X.BADGES = badges;
      const rated = B.teams.filter((t) => X.ratingIdx()[t.team]).length;
      const real = B.teams.filter((t) => t.real && t.real.pl).length;
      const withXg = B.teams.filter((t) => t.real && t.real.gf != null && t.real.n_xg).length;
      const withShots = B.teams.filter((t) => t.real && t.real.n_stats && t.real.shots).length;
      const expect = {ad: rated, xp: real, gx: withXg, sq: withShots, fp: B.teams.length, ev: rated};
      const counts = X.VIZ.map(([k]) => {
        if (["ri","atlas","density","rivals","entryroutes","timing","trajectory","expectation","quality","tmbridge","tmfates","tmstrength"].includes(k)) return [k, null];            // a grid, not marks: it has its own check below
        const evidenceModes={xp:'points',gx:'goals',sq:'quality',fm:'form'};
        if(evidenceModes[k]){
          const markup=X.vizHtml(B,kind,k,null),mode=evidenceModes[k];
          expect[k]='evidence '+mode;
          const roots=(markup.match(/\bdata-competition-evidence\b/g)||[]).length;
          return [k,roots===1&&markup.includes('data-evidence-comp="'+Workspace.esc(B.competition)+'"')&&markup.includes('data-evidence-mode="'+mode+'"')&&!markup.includes('data-chart-picker')?'evidence '+mode:'invalid evidence root'];
        }
        if (k === "pr") {
          if (!g) return [k, null];
          // a line chart: one faint line for each side not lit, and the lit ones
          const html = X.vizHtml(B, kind, k, g);
          const lit = (html.match(/<button data-hl="[^"]*" aria-pressed="true"/g) || []).length;
          const faint = (html.match(/<path [^>]*data-hl=/g) || []).length;
          expect[k] = g.teams.length;
          return [k, lit >= 1 && lit <= 4 ? faint + lit : `lit ${lit}`];
        }
        if (k === "rt") {
          if (!g || !Array.isArray(g.elo)) return [k, null];
          // one chip per side, and one faint line for every side not lit
          const html = X.vizHtml(B, kind, k, g);
          const chips = (html.match(/<button data-hl=/g) || []).length;
          const lit = (html.match(/<button data-hl="[^"]*" aria-pressed="true"/g) || []).length;
          const faint = (html.match(/<path [^>]*data-hl=/g) || []).length;
          expect.rt = `${g.teams.length}+${g.teams.length - lit}`;
          return [k, lit >= 1 && lit <= 4 ? `${chips}+${faint}` : `lit ${lit}`];
        }
        return [k, (X.vizHtml(B, kind, k, g).match(/class="hit"/g) || []).length];
      });
      const badChart = counts.filter(([k, n]) => n !== null && n !== expect[k]);
      check(!badChart.length, `${B.competition}: every chart draws one mark per side (${tag}: `
            + counts.map(([k, n]) => `${k} ${n}`).join(", ") + ")",
            badChart.map(([k, n]) => `${k} ${n} want ${expect[k]}`).join("; "));
      if (tag === "badges") {
        const imgs = (X.vizHtml(B, kind, "ad", g).match(/<image /g) || []).length;
        check(imgs === rated, `${B.competition}: with badges every side is a badge (${imgs})`);
      }
    }
  }
  X.BADGES = {};
}

// ---------------------------------------------------------------- xG by round, stats hub, all-competition charts
// Version 9. Every match is counted for both sides, so a block's xG for = xG against at every
// round; at the last round played in full each side's x+ and xG PTS are its played matches' sums;
// and the points race ends on the projection's own XPTS. The hub's tables are square and its
// shot totals balance; the all-competition charts draw every side and every title race sums to 1.
if (GWD && Object.values(GWD.leagues).some((g) => Array.isArray(g.xgf))) {
  let worstBal = 0, worstReal = 0, worstEnd = 0, at0 = "";
  for (const [comp, g] of Object.entries({...GWD.leagues, ...(GWD.phases || {})})) {
    if (!Array.isArray(g.xgf)) continue;
    for (let at = 0; at <= g.rounds; at++) {
      const d = Math.abs(g.xgf.reduce((a, r) => a + r[at], 0) - g.xga.reduce((a, r) => a + r[at], 0));
      if (d > worstBal) worstBal = d;
    }
    const full = X.lastFullRound(g);
    g.teams.forEach((team, i) => {
      const mine = g.fixtures.filter((f) => f.result && f.xpts && f.round <= full && (f.home === team || f.away === team));
      const sx = mine.reduce((a, f) => a + (f.home === team ? f.xg[0] : f.xg[1]), 0);
      const sp = mine.reduce((a, f) => a + (f.home === team ? f.xpts[0] : f.xpts[1]), 0);
      const d = Math.max(Math.abs(sx - g.xgf[i][full]), Math.abs(sp - g.xgpts[i][full]));
      if (d > worstReal) { worstReal = d; at0 = `${comp} ${team}`; }
    });
    const L = RESULT.leagues.find((l) => l.competition === comp) || RESULT.uefa.find((u) => u.competition === comp);
    if (L) L.teams.forEach((t) => {
      const i = g.teams.indexOf(t.team);
      if (i >= 0 && t.mean_pts != null) worstEnd = Math.max(worstEnd, Math.abs(3 * g.w[i][g.rounds] + g.d[i][g.rounds] - t.mean_pts));
    });
  }
  // two-decimal means over up to 36 sides; three-decimal xG points summed over a few matches
  check(worstBal < 0.2 && worstReal < 0.06 && worstEnd < 0.16,
        `xG by round: for = against at every round (worst ${worstBal.toFixed(2)}); at the last full round x+ and`
        + ` xG PTS are the played matches' sums (worst ${worstReal.toFixed(3)}); the points race ends on XPTS`
        + ` (worst ${worstEnd.toFixed(2)})`, at0);
} else {
  console.log("  skip    xG-by-round checks (a snapshot before version 9)");
}
{
  const blocks = [...RESULT.leagues, ...RESULT.uefa].filter((B) => B.teams.some((t) => t.real && t.real.n_stats));
  let off = 0, sq = [];
  for (const B of blocks) {
    for (const k of ["shots", "sot", "bigch", "corners"]) {
      off = Math.max(off, Math.abs(B.teams.reduce((a, t) => a + ((t.real || {})[k] || 0) - ((t.real || {})[k + "_a"] || 0), 0)));
    }
    for (const sub of ["team", "leaders", "venue"]) {
      X.HUBSEL = sub;
      delete els.cview;
      X.drawStatsHub(B);
      const html = mk("cview").innerHTML;
      for (const tbl of html.split("<table").slice(1)) {
        const head = tbl.slice(0, tbl.indexOf("</thead>"));
        const hrows = head.split("<tr>").slice(1), last = hrows[hrows.length - 1];
        const heads = (last.match(/<th\b/g) || []).length;
        const rows = tbl.slice(tbl.indexOf("<tbody>"), tbl.indexOf("</tbody>")).split("<tr>").slice(1);
        if (!rows.length || rows.some((r) => (r.match(/<td\b/g) || []).length !== heads)) sq.push(`${B.competition} ${sub}`);
      }
    }
  }
  X.HUBSEL = "team";
  if (blocks.length) {
    check(off === 0 && !sq.length, `stats hub: in ${blocks.length} competitions shots, on target, big chances and`
          + ` corners for = against; every table square`, `off ${off}; not square: ${sq.slice(0, 3).join(", ")}`);
  } else {
    console.log("  skip    stats hub checks (a snapshot before version 9)");
  }
}
if (RESULT.ratings) {
  const sides = RESULT.ratings.teams.filter((r) => r.league).length;
  X.VIZSEL = "xa"; delete els.view; X.drawAllViz();
  const xa = (mk("view").innerHTML.match(/class="hit"/g) || []).length;
  X.VIZSEL = "ls"; delete els.view; X.drawAllViz();
  const ls = (mk("view").innerHTML.match(/class="hit"/g) || []).length;
  // its markers, read off the chart: for every league, on either scale, the best five average at
  // least the best ten and the best ten at least the whole league (a mean of a top-k only falls as
  // k grows) -- and each value is that league's own, recomputed here
  const marksOff = [];
  const readMarks = (metric) => {
    const html = mk("view").innerHTML;
    const got = {};
    for (const m of html.matchAll(/data-ls="([^|]+)\|([^|]+)\|([-\d.]+)"/g)) (got[m[1]] ||= {})[m[2]] = +m[3];
    for (const L of RESULT.leagues) {
      const v = RESULT.ratings.teams.filter((r) => r.league === L.competition)
        .map((r) => metric === "elo" ? r.elo : r.att - r.def).sort((a, b) => b - a);
      const mean = (a) => a.reduce((x, y) => x + y, 0) / a.length;
      const want = {"mean": mean(v), "top 10": mean(v.slice(0, 10)), "top 5": mean(v.slice(0, 5))};
      const g = got[L.competition] || {};
      if (!(g["top 5"] >= g["top 10"] && g["top 10"] >= g["mean"])
          || Object.keys(want).some((k) => Math.abs((g[k] ?? NaN) - want[k]) > 1e-3)) marksOff.push(`${metric} ${L.competition}`);
    }
  };
  readMarks("net");
  X.VIZOPT.lsm = "elo"; delete els.view; X.drawAllViz();
  const lsElo = (mk("view").innerHTML.match(/class="hit"/g) || []).length;
  readMarks("elo");
  X.VIZOPT.lsm = "net";
  check(!marksOff.length, `league strength: every league's mean, top 10 and top 5 are its own, top 5 ≥ top 10 ≥ mean, on NET and Elo`,
        marksOff.slice(0, 3).join(", "));
  const races = RESULT.leagues.map((L) => L.teams.reduce((a, t) => a + (t.p_win || 0), 0));
  check(xa === sides && ls === sides && lsElo === sides && races.every((x) => Math.abs(x - 1) < 2e-3),
        `all competitions: attack v defence and league strength (NET and Elo) draw all ${sides} league sides; every title race sums to 100%`,
        `xa ${xa}, ls ${ls}, ls elo ${lsElo}, races ${races.map((x) => x.toFixed(3))}`);
  X.VIZSEL = "ad";
}

// ---------------------------------------------------------------- the round's decisions and its xG
// Title / Down are cumulative -- settled by the end of the round -- so down the gameweeks each
// side's cell never falls, and the Final table's are the projection's own TITLE and REL (every
// world settles its title once, for its champion). A played match's xG, shown beside its score
// from the row's side, is the payload's fixture turned round for the away row -- and, at a round
// played in full, the step in that side's x+ over the round: two independently written fields.
if (GWD) {
  const num = (s) => { const t = clean(s); return t === "·" || t === "" ? 0 : parseFloat(t); };
  let blocks = 0, falls = [], ends = [], worstEnd = 0, xgCells = 0, xgOff = [], xgWant = 0, projXg = 0;
  for (const [comp, g] of Object.entries({...GWD.leagues, ...(GWD.phases || {})})) {
    const L = RESULT.leagues.find((l) => l.competition === comp);
    const prev = {};
    const full = X.lastFullRound(g);
    for (let x = 1; x <= g.rounds + 1; x++) {
      const rows = rowsOf(X.gwTable(g, x, GWD.worlds));
      const h = rows[1].map(clean), iT = h.indexOf("Title"), iD = h.indexOf("Down"), iO = h.indexOf("Opponent");
      for (const c of rows.slice(2)) {
        const team = clean(c[0]), i = g.teams.indexOf(team);
        if (g.clinch && iT >= 0) {
          const v = [num(c[iT]), num(c[iD])];
          if (prev[team] && (v[0] < prev[team][0] - 1e-9 || v[1] < prev[team][1] - 1e-9)) falls.push(`${comp} ${team} GW ${x}`);
          prev[team] = v;
          if (x > g.rounds && L) {
            const t = L.teams.find((r) => r.team === team);
            const n = (g.clinch.filter(([k]) => k === i).length + g.down.filter(([k]) => k === i).length);
            const d = Math.max(Math.abs(v[0] - 100 * t.p_win), Math.abs(v[1] - 100 * t.p_releg));
            worstEnd = Math.max(worstEnd, d);
            // the cell's half-unit, plus each four-place entry summed into it
            if (d > 0.05 + n * 0.005 + 0.005 + 1e-9) ends.push(`${comp} ${team} ${v.join("/")}`);
          }
        }
        if (iO < 0 || x > g.rounds) continue;
        const m = c[iO].match(/>xG ([\d.]+)–([\d.]+)</);
        const f = g.fixtures.find((f) => f.round === x && f.result && (f.home === team || f.away === team));
        const has = f && Array.isArray(f.xg) && f.xg.every((v) => v != null);
        if (has) xgWant++;
        if (m && !f) {
          // a match to come (version 10): its xG is the side's own steps over the round
          const st = Array.isArray(g.xgf) ? [g.xgf[i][x] - g.xgf[i][x - 1], g.xga[i][x] - g.xga[i][x - 1]] : null;
          projXg++;
          if (!st || Math.abs(+m[1] - st[0]) > 0.05 + 1e-9 || Math.abs(+m[2] - st[1]) > 0.05 + 1e-9) {
            xgOff.push(`${comp} ${team} GW ${x} projected ${m[1]}–${m[2]} not its steps`);
          }
          continue;
        }
        if (!m) { if (has) xgOff.push(`${comp} ${team} GW ${x} no xG shown`); continue; }
        xgCells++;
        const [a, b] = [+m[1], +m[2]];
        const mine = f.home === team ? f.xg : [f.xg[1], f.xg[0]];
        if (Math.abs(a - mine[0]) > 0.05 + 1e-9 || Math.abs(b - mine[1]) > 0.05 + 1e-9) xgOff.push(`${comp} ${team} GW ${x} ${a}–${b} not its fixture`);
        const step = Array.isArray(g.xgf) && x <= full ? [g.xgf[i][x] - g.xgf[i][x - 1], g.xga[i][x] - g.xga[i][x - 1]] : null;
        // the cell's half-unit and the two two-place run totals
        if (step && (Math.abs(a - step[0]) > 0.05 + 0.01 + 1e-9 || Math.abs(b - step[1]) > 0.05 + 0.01 + 1e-9)) {
          xgOff.push(`${comp} ${team} GW ${x} ${a}–${b} not the x+ step ${step.map((v) => v.toFixed(2)).join("–")}`);
        }
      }
    }
    if (g.clinch) blocks++;
  }
  if (blocks) {
    check(!falls.length && !ends.length,
          `gameweek: in ${blocks} leagues Title / Down never fall round to round, and the Final table's are TITLE and REL`
          + ` (worst ${worstEnd.toFixed(3)}pp)`, `${falls.length} fall, ${ends.length} ends off, e.g. ${[...falls, ...ends].slice(0, 3).join("; ")}`);
  } else {
    console.log("  skip    gameweek Title / Down (a snapshot before the clinch counts)");
  }
  if (Object.values(GWD.leagues).some((g) => g.fixtures.some((f) => f.result && f.xg))) {
    check(xgCells > 0 && xgCells === xgWant && !xgOff.length,
          `gameweek: ${xgCells} rows of played matches show the xG beside the score, from the row's side, each the step in its x+;`
          + ` ${projXg} rows to come show their own steps`,
          `${xgOff.length} off (${xgCells} shown of ${xgWant}), e.g. ${xgOff.slice(0, 3).join("; ")}`);
  } else {
    console.log("  skip    played-match xG (a snapshot before version 9)");
  }
}

// ---------------------------------------------------------------- fixtures, stakes, change windows
// Version 10. Read off the rendered Fixtures view of every league and league phase, at a round
// played in full and the next one to play: each of its matches once, the result chances summing
// to 100%, a played match's xG its payload's, a projected one's the home side's steps in x+/x−
// -- and its x− the AWAY side's x+ step, two sides' run totals written separately. Each shown
// swing is the widest its stakes allow; weighted by the results' chances, the stakes give back
// the projection's own P(fate). The Big matches tab is in swing order, inside its window.
if (GWD && Object.values(GWD.leagues).some((g) => g.fixtures.some((f) => f.stakes))) {
  X.GW = GWD;
  const fate = {title: (T) => T.p_win, ucl: (T) => T.p_ucl, euro: (T) => T.p_ucl + T.p_uel + T.p_uecl,
                down: (T) => T.p_releg, top8: (T) => T.p_top8, top24: (T) => 1 - T.p_out,
                r16: (T) => T.p_r16, win: (T) => T.p_win};
  const cells = (html) => html.split("<tbody>")[1].split("</tbody>")[0].split(/<tr\b[^>]*>/).slice(1)
    .map((r) => [...r.matchAll(/<td\b([^>]*)>([\s\S]*?)<\/td>/g)].map((m) => ({attr: m[1], txt: m[2].replace(/<[^>]*>/g, "").trim()})));
  const headsOf = (html) => [...html.split("<thead>")[1].split("</thead>")[0].matchAll(/<th\b[^>]*>([\s\S]*?)<\/th>/g)]
    .map((m) => m[1].replace(/<[^>]*>/g, "").trim());
  let tables = 0, rows = 0, off = [], stN = 0, stWorst = 0, xgN = 0;
  for (const [kind, blocks] of [["league", GWD.leagues], ["uefa", GWD.phases || {}]]) {
    for (const [comp, g] of Object.entries(blocks)) {
      const B = [...RESULT.leagues, ...RESULT.uefa].find((b) => b.competition === comp);
      const T = Object.fromEntries(B.teams.map((t) => [t.team, t]));
      const keys = g.stakes_of || X.STAKES_OF[kind];
      for (const f of g.fixtures) {
        if (f.result || !f.stakes) continue;
        const po = [f.ladder.h1, f.ladder.d, f.ladder.a1];
        f.stakes.forEach((side, k) => side.forEach((v, j) => {
          const r = Array.isArray(v) ? v : [v, v, v];
          const got = r.reduce((a, x, o) => a + po[o] * (x || 0), 0);
          const d = Math.abs(got - fate[keys[j]](T[k ? f.away : f.home]));
          stN++; stWorst = Math.max(stWorst, d);
        }));
      }
      const full = X.lastFullRound(g);
      for (const x of [full, Math.min(full + 1, g.rounds)].filter((r) => r >= 1)) {
        X.GW = GWD; X.FXMODE = "round"; X.GWSEL[comp] = x;
        delete els.cview;
        await X.drawFixtures(B, kind);
        const html = mk("cview").innerHTML;
        if (!html.includes("<tbody>")) { off.push(`${comp} GW ${x} no table`); continue; }
        const H = headsOf(html), C = cells(html);
        tables++;
        const want = g.fixtures.filter((f) => f.round === x);
        const iH = H.indexOf("H"), iX = H.indexOf("xG"), iS = H.indexOf("SWING");
        if (C.some((r) => r.length !== H.length) || C.length !== want.length) off.push(`${comp} round of ${C.length} rows, want ${want.length}`);
        for (const r of C) {
          rows++;
          const f = g.fixtures.find((q) => q.home === r[1].txt && q.away === r[3].txt);
          if (!f) { off.push(`${comp} ${r[1].txt} v ${r[3].txt} not a fixture`); continue; }
          const hda = [r[iH], r[iH + 1], r[iH + 2]].map((c) => c.txt);
          if (f.result) {
            if (hda.filter((t) => t === "✓").length !== 1) off.push(`${comp} ${f.home} v ${f.away} ticks`);
            if (f.xg && r[iX].txt !== `${f.xg[0].toFixed(1)}–${f.xg[1].toFixed(1)}`) off.push(`${comp} ${f.home} xG ${r[iX].txt}`);
          } else {
            const sum = hda.reduce((a, t) => a + parseFloat(t), 0);
            if (Math.abs(sum - 100) > 0.2) off.push(`${comp} ${f.home} v ${f.away} H+D+A ${sum}`);
            const hi = g.teams.indexOf(f.home), ai = g.teams.indexOf(f.away);
            // the steps, read here off the payload rather than through the page's own helper
            const step = (i) => [g.xgf[i][f.round] - g.xgf[i][f.round - 1], g.xga[i][f.round] - g.xga[i][f.round - 1]];
            if (Array.isArray(g.xgf)) {
              const sh = step(hi), sa = step(ai);
              const [a, b] = r[iX].txt.split("–").map(Number);
              xgN++;
              // the shown 1dp against the home side's steps; the home x− against the away x+ (2dp each)
              if (Math.abs(a - sh[0]) > 0.05 + 1e-9 || Math.abs(b - sh[1]) > 0.05 + 1e-9
                  || Math.abs(sh[1] - sa[0]) > 0.011 || Math.abs(sh[0] - sa[1]) > 0.011) {
                off.push(`${comp} ${f.home} v ${f.away} xG ${r[iX].txt} steps ${sh.map((v) => v.toFixed(2))} / ${sa.map((v) => v.toFixed(2))}`);
              }
            }
            // the widest swing, recomputed off the payload: over both sides and every fate
            let widest = 0, at = null;
            f.stakes.forEach((side, k) => side.forEach((v, j) => {
              const r3 = (Array.isArray(v) ? v : [v, v, v]).filter((q) => q != null);
              const w = Math.max(...r3) - Math.min(...r3);
              if (w > widest + 1e-12) { widest = w; at = {k, j, v}; }
            }));
            const shown = r[iS].txt === "—" ? 0 : parseFloat(r[iS].txt);
            if (Math.abs(shown - (widest >= 0.005 ? 100 * widest : 0)) > 0.05 + 1e-9) off.push(`${comp} ${f.home} swing ${shown} not ${(100 * widest).toFixed(1)}`);
            // and the stake it names: that side, that fate, its chance with a win and a loss --
            // the payload's [home win, draw, away win] turned round for the away side
            if (widest >= 0.005) {
              const team = at.k ? f.away : f.home, v = at.v;
              const win = at.k ? v[2] : v[0], loss = at.k ? v[0] : v[2];
              const txt = r[iS - 1].txt.replace(/\s+/g, " ");
              const want = `${X.shortName(team)} ${X.stakeName(keys[at.j])} ${(100 * win).toFixed(0)}% win · ${(100 * loss).toFixed(0)}% loss`;
              if (txt !== want) off.push(`${comp} stake "${txt}" not "${want}"`);
            }
          }
        }
      }
    }
  }
  // the run-in grid: every projected fixture fills two cells, and the home cell's W is the away
  // cell's L -- the fixture turned round
  let riCells = 0, riWant = 0;
  const riOff = [];
  for (const [kind, blocks] of [["league", GWD.leagues], ["uefa", GWD.phases || {}]]) {
    for (const [comp, g] of Object.entries(blocks)) {
      const B = [...RESULT.leagues, ...RESULT.uefa].find((b) => b.competition === comp);
      const html = X.vizHtml(B, kind, "ri", g);
      const seen = {};
      for (const m of html.matchAll(/data-ri="([^|"]+)\|([^|"]+)\|([^|"]+)\|([^"]+)"/g)) {
        riCells++;
        seen[`${m[1].replace(/&amp;/g, "&")}|${m[2].replace(/&amp;/g, "&")}`] = [+m[3], +m[4]];
      }
      for (const f of g.fixtures.filter((q) => !q.result)) {
        riWant += 2;
        const h = seen[`${f.home}|${f.away}`], a = seen[`${f.away}|${f.home}`];
        if (!h || !a || Math.abs(h[0] - a[1]) > 1e-9 || Math.abs(h[1] - a[0]) > 1e-9) riOff.push(`${comp} ${f.home} v ${f.away}`);
      }
    }
  }
  check(riCells > 0 && riCells === riWant && !riOff.length, `run-in: ${riCells} cells, two a projected fixture, the home W the away L`,
        `${riCells} of ${riWant}; ${riOff.slice(0, 3).join("; ")}`);
  check(tables > 0 && rows > 0 && !off.length, `fixtures: ${tables} rendered rounds, ${rows} matches — each once,`
        + ` H+D+A = 100%, xG the payload's or the home side's steps (and its x− the away x+, ${xgN} projected), every swing its stakes' widest`,
        `${off.length} off, e.g. ${off.slice(0, 3).join("; ")}`);
  check(stN > 1000 && stWorst < 2e-3, `stakes: over ${stN} side-fates, Σ P(result) P(fate | result) = P(fate) (worst ${stWorst.toFixed(4)})`);
  // the Big matches tab: each competition's widest swings, in tab order, at most 3 (the week) or 5
  // (the season) each, in swing order inside it, the week's inside its week
  let bigOff = [], bigN = 0;
  for (const [mode, per] of [["week", 3], ["season", 5]]) {
    X.BIGMODE = mode;
    delete els.view;
    await X.drawBigMatches();
    const html = mk("view").innerHTML;
    if (!html.includes("<tbody>")) { bigOff.push(`${mode} empty`); continue; }
    const H = headsOf(html), C = cells(html), iS = H.indexOf("SWING");
    bigN += C.length;
    const comps = C.map((r) => r[0].txt), order = X.COMP_ORDER.map((c) => c);
    const seen = [...new Set(comps)];
    const labelOf = (c) => order.find((o) => (o.replace(/^(UEFA|English|Spanish|Italian|German|French) /, "") === c) || o.endsWith(c)) || c;
    if (seen.some((c, k) => k && order.indexOf(labelOf(c)) < order.indexOf(labelOf(seen[k - 1])))) bigOff.push(`${mode} competitions out of tab order`);
    for (const c of seen) {
      const sw = C.filter((r) => r[0].txt === c).map((r) => parseFloat(r[iS].txt));
      if (sw.length > per || sw.some((v, k) => k && v > sw[k - 1] + 1e-9)) bigOff.push(`${mode} ${c} ${sw.join("/")}`);
      if (comps.lastIndexOf(c) - comps.indexOf(c) + 1 !== sw.length) bigOff.push(`${mode} ${c} split`);
    }
    if (mode === "week") {
      const stop = new Date(RESULT.as_of + "T00:00:00"); stop.setDate(stop.getDate() + 8);
      if (C.some((r) => r[1].attr.match(/data-v="([^"]+)"/)[1].slice(0, 10) >= stop.toISOString().slice(0, 10))) bigOff.push("a match outside the week");
    }
  }
  X.BIGMODE = "week";
  check(bigN > 0 && !bigOff.length, `big matches: ${bigN} rows, each competition's widest swings in tab order, 3 (week) or 5 (season) at most, in swing order, the week's inside it`,
        bigOff.join("; "));
  // change windows: each Δ heading names the window picked, and the snapshot it reads is the
  // latest whose data ended on or before the window's start (or the season's first)
  const wins = X.windowsOf();
  const winOff = [];
  for (const w of wins) {
    X.DWIN = w.key;
    const headLeague = X.league(RESULT.leagues[0]);
    if (!headLeague.includes(`Δ ${({"1w": "1W", "1m": "1M", "3m": "3M", season: "SEASON"})[w.key]}`)) winOff.push(`${w.key} heading`);
    const k = X.snapAt(w), meta = HISTORY.meta || {}, dates = HISTORY.dates || [];
    const asOf = (i) => (meta[dates[i]] || {}).as_of || dates[i];
    if (k < 0 || (asOf(k) > w.date && k !== 0) || (k + 1 < dates.length && asOf(k + 1) <= w.date && dates[k + 1] < (RESULT.source || {}).date)) winOff.push(`${w.key} reads ${dates[k]}`);
  }
  X.DWIN = "1w";
  check(wins.length > 0 && !winOff.length, `change windows: ${wins.length} Δ headings name their window; each reads its own snapshot`, winOff.join("; "));
} else {
  console.log("  skip    fixtures and stakes checks (a snapshot before version 10)");
}

// Going in: the last round's Title is the chance settled BEFORE it -- the Final's less the final
// day's share. Read through the round instead, GW 38 equalled the Final (the owner's catch).
if (GWD) {
  let n = 0, worst = 0;
  const offIn = [];
  for (const [comp, g] of Object.entries(GWD.leagues)) {
    if (!g.clinch) continue;
    const rows = rowsOf(X.gwTable(g, g.rounds, GWD.worlds));
    const iT = rows[1].map(clean).indexOf("Title");
    for (const c of rows.slice(2)) {
      const i = g.teams.indexOf(clean(c[0]));
      const mine = g.clinch.filter(([k, r]) => k === i && r < g.rounds);
      const before = 100 * mine.reduce((a, [, , p]) => a + p, 0);
      const t = clean(c[iT]), shown = t === "·" || t === "" ? 0 : parseFloat(t);
      n++; worst = Math.max(worst, Math.abs(shown - before));
      if (Math.abs(shown - before) > 0.05 + mine.length * 0.005 + 1e-9) offIn.push(`${comp} ${clean(c[0])} ${shown} not ${before.toFixed(2)}`);
    }
  }
  if (n) check(!offIn.length, `gameweek: the last round's Title is what was settled before it, ${n} sides (worst ${worst.toFixed(3)}pp)`, offIn.slice(0, 3).join("; "));
}

// ---------------------------------------------------------------- knockout charts
// For every cup and UEFA competition, read off the rendered charts: one line per side on the road
// to the final; the two sides of every drawn tie summing to 100% to go through; the two sides of
// every likely final summing to 100% to win it; and each stage holding exactly its sides --
// 36 / 24 / 16 / 8 / 4 / 2 / 1 for UEFA, 2 and 1 for any final and its winner.
{
  const PD = typeof PATHSD !== "undefined" ? PATHSD : null;
  const pctOf = (cell) => parseFloat(cell.replace(/<[^>]*>/g, ""));
  const cellsOf = (html) => html.split("<tbody>")[1].split("</tbody>")[0].split("<tr>").slice(1)
    .map((r) => [...r.matchAll(/<td\b[^>]*>([\s\S]*?)<\/td>/g)].map((m) => m[1]));
  let nTies = 0, tieOff = [], nFinals = 0, finalOff = [], lineOff = [], stageOff = [], swOff = [];
  for (const B of [...CUPS, ...RESULT.uefa]) {
    const kind = CUPS.includes(B) ? "cup" : "uefa";
    const {teams, stages} = X.koStages(B);
    const ko = X.vizHtml(B, kind, "ko");
    const faint = (ko.match(/<path [^>]*data-hl=/g) || []).length;
    const lit = (ko.match(/stroke-width="2.25"/g) || []).length;
    if (faint + lit !== teams.length) lineOff.push(`${B.competition} ${faint}+${lit} of ${teams.length}`);
    const nt = X.vizHtml(B, kind, "nt");
    if (nt.includes("<tbody>")) {
      for (const c of cellsOf(nt)) {
        nTies++;
        if (Math.abs(pctOf(c[1]) + pctOf(c[3]) - 100) > 0.15) tieOff.push(`${B.competition} ${c[0].replace(/<[^>]*>/g, "")}`);
      }
    }
    const P = PD ? ((kind === "uefa" ? PD.competitions : PD.cups) || {})[B.competition] : null;
    const kf = X.vizHtml(B, kind, "kf", null, P);
    if (P && kf.includes("<tbody>")) {
      for (const c of cellsOf(kf)) {
        if (c[6].includes("—") || c[7].includes("—")) continue;
        nFinals++;
        if (Math.abs(pctOf(c[6]) + pctOf(c[7]) - 100) > 0.25) finalOff.push(`${B.competition} ${c[1].replace(/<[^>]*>/g, "")}`);
      }
    }
    const os = X.vizHtml(B, kind, "os");
    const counts = [...os.matchAll(/data-os="([\d.]+)\|([\d.]+)"/g)].map((m) => [+m[1], +m[2]]);
    const want = kind === "uefa" ? [36, 24, 16, 8, 4, 2, 1] : null;
    counts.forEach(([o, a], k) => {
      const w = want ? want[k] : (k === counts.length - 1 ? 1 : k === counts.length - 2 ? 2 : null);
      if (o > a + 1e-9 || (w != null && Math.abs(a - w) > 0.01)) stageOff.push(`${B.competition} ${stages[k][0]} ${o}/${a}`);
    });
    const rated = teams.filter((t) => X.ratingIdx()[t.team]).length;
    const sw = (X.vizHtml(B, kind, "sw").match(/class="hit"/g) || []).length;
    if (RESULT.ratings && sw !== rated) swOff.push(`${B.competition} ${sw} of ${rated}`);
  }
  check(!lineOff.length, `knockouts: the road to the final draws one line per side in ${CUPS.length + RESULT.uefa.length} competitions`,
        lineOff.slice(0, 3).join("; "));
  check(!tieOff.length, `knockouts: the two sides of each of ${nTies} drawn ties sum to 100% to go through`,
        tieOff.slice(0, 3).join("; "));
  check(!PD || (nFinals > 0 && !finalOff.length), `knockouts: the two sides of each of ${nFinals} likely finals sum to 100% to win it`,
        finalOff.slice(0, 3).join("; "));
  check(!stageOff.length, `knockouts: every stage holds exactly its sides (UEFA 36/24/16/8/4/2/1, any final 2 and its winner 1), outsiders inside them`,
        stageOff.slice(0, 3).join("; "));
  check(!swOff.length, `knockouts: strength v trophy chance draws every rated side`, swOff.slice(0, 3).join("; "));
}

// ---------------------------------------------------------------- goals against xG
// Version 8. Every match is counted for both of its sides, so over a competition the totals
// balance exactly -- goals for = against, xG = xGA, xG on target = xGOTA, penalties taken = faced
// -- and a league side's goals are its real table's.
const withGoals = [...RESULT.leagues, ...RESULT.uefa].filter((B) => B.teams.some((t) => t.real && t.real.gf != null));
if (!withGoals.length) {
  console.log("  skip    goals v xG checks (a snapshot before version 8)");
} else {
  let worst = 0, at = "", tableOff = [];
  for (const B of withGoals) {
    const sum = (k) => B.teams.reduce((a, t) => a + ((t.real || {})[k] || 0), 0);
    for (const [x, y] of [["gf", "ga"], ["xg", "xga"], ["xgot", "xgota"], ["pens", "pens_a"]]) {
      const d = Math.abs(sum(x) - sum(y));
      if (d > worst) { worst = d; at = `${B.competition} ${x}`; }
    }
    if (RESULT.leagues.includes(B)) {
      tableOff.push(...B.teams.filter((t) => t.real && t.now && t.real.pl === t.now.pl
        && (t.real.gf !== t.now.gf || t.real.ga !== t.now.ga)).map((t) => t.team));
    }
  }
  // Version 10: penalty goals off the shot maps. Over a competition the scored ones balance like
  // goals, and no side scores more penalties than it took or more than its goals.
  const pgBlocks = withGoals.filter((B) => B.teams.some((t) => t.real && t.real.pen_g != null));
  const pgOff = [];
  for (const B of pgBlocks) {
    const sum = (k) => B.teams.reduce((a, t) => a + ((t.real || {})[k] || 0), 0);
    if (sum("pen_g") !== sum("pen_g_a")) pgOff.push(`${B.competition} unbalanced`);
    for (const t of B.teams) {
      const r = t.real || {};
      if (r.pen_g != null && (r.pen_g > r.pens || r.pen_g_a > r.pens_a || r.pen_g > r.gf || r.pen_g_a > r.ga)) pgOff.push(`${B.competition} ${t.team}`);
    }
  }
  if (pgBlocks.length) {
    check(!pgOff.length, `penalty goals: in ${pgBlocks.length} competitions scored = conceded, none above the penalties taken or the goals`,
          pgOff.slice(0, 3).join("; "));
  } else {
    console.log("  skip    penalty goals (a snapshot before version 10)");
  }
  // xG totals are each rounded to two places, over up to 36 sides
  check(worst < 0.2 && !tableOff.length, `goals v xG: in ${withGoals.length} competitions goals for = against,`
        + ` xG = xGA, xGOT = xGOTA, penalties taken = faced (worst gap ${worst.toFixed(2)}${at ? " " + at : ""});`
        + ` every league side's goals are its table's`, `${tableOff.length} differ from the table, e.g. ${tableOff.slice(0, 3)}`);
}

// ---------------------------------------------------------------- trophies
// One champion per competition per world: the expected hauls sum to the number of competitions
// decided, every team's 0/1/2... chances sum to 1, and its listed hauls plus the pooled rest are
// exactly its chance of winning anything.
if (RESULT.trophies) {
  const T = RESULT.trophies;
  const total = T.teams.reduce((a, t) => a + t.mean, 0) + ((T.others || {}).mean || 0);
  const comps = RESULT.leagues.length + RESULT.uefa.length + CUPS.length;
  check(Math.abs(total - T.per_world) < 0.01 && Math.abs(T.per_world - comps) < 1e-9,
        `trophies: expected hauls sum to ${total.toFixed(3)}, the ${comps} competitions decided`);
  const off = T.teams.filter((t) => Math.abs(t.p.reduce((a, b) => a + b, 0) - 1) > 1e-3
    || Math.abs(t.combos.reduce((a, [, p]) => a + p, 0) + t.other - (1 - t.p[0])) > 2e-3);
  check(!off.length, `trophies: every team's counts sum to 1 and its hauls to P(at least one)`
        + ` (${T.teams.length} teams)`, off.slice(0, 3).map((t) => t.team).join(", "));
  delete els.view;
  X.drawTrophies();
  const markup = mk("view").innerHTML;
  const tbls = markup.split("<table").slice(1);
  const square = tbls.every((tbl) => {
    const head = tbl.slice(0, tbl.indexOf("</thead>"));
    const heads = (head.match(/<th\b/g) || []).length;
    const rows = tbl.slice(tbl.indexOf("<tbody>"), tbl.indexOf("</tbody>")).split("<tr>").slice(1);
    return rows.length && rows.every((r) => (r.match(/<td\b/g) || []).length === heads);
  });
  check(tbls.length === 2 && square, `trophies: both tables render square`);
}

// ---------------------------------------------------------------- movers
// The probability change is the same number on the Overview and Movers, including the exact
// snapshot chosen for the window. Check the rendered cells as well as the ordering and counts:
// an all-zero or empty list must not quietly pass as a list of the biggest movers.
{
  X.GW = GWD;
  const unesc = (s) => s.replace(/&quot;/g, '"').replace(/&#39;/g, "'")
    .replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&amp;/g, "&");
  const attrsOf = (s) => Object.fromEntries([...s.matchAll(/([\w-]+)="([^"]*)"/g)]
    .map((m) => [m[1], unesc(m[2])]));
  const textOf = (s) => unesc(s.replace(/<[^>]*>/g, "")).trim();
  const numberOf = (s) => {
    const t = textOf(s);
    if (t === "—" || t === "") return null;
    const v = parseFloat(t.replace(/[▲▼%]/g, "").replace(/−/g, "-"));
    return t.includes("▼") ? -v : v;
  };
  const tablesOf = (html) => [...html.matchAll(/<table\b([^>]*)>([\s\S]*?)<\/table>/g)]
    .map((m) => ({attr: attrsOf(m[1]), body: m[2]})).filter((t) => t.attr["data-movers"]);
  const rowsIn = (table) => [...(table.body.match(/<tbody[^>]*>([\s\S]*?)<\/tbody>/) || [, ""])[1]
    .matchAll(/<tr\b([^>]*)>([\s\S]*?)<\/tr>/g)].map((m) => {
      const cells = [...m[2].matchAll(/<td\b([^>]*)>([\s\S]*?)<\/td>/g)]
        .map((c) => ({attr: attrsOf(c[1]), html: c[2]}));
      const team = cells.findIndex((c) => c.attr["data-team"] != null);
      return {attr: attrsOf(m[1]), cells, team: team < 0 ? null : cells[team].attr["data-team"],
        then: cells[team + 1], now: cells[team + 2], delta: cells[team + 3],
        elo: cells[team + 4], results: cells[team + 5]};
    });
  const specs = {
    title: [...RESULT.leagues, ...RESULT.uefa].map((b) => [b, "p_win"]),
    europe: [...RESULT.leagues.map((b) => [b, "p_ucl"]), ...RESULT.uefa.map((b) => [b, "p_top8"])],
    survival: RESULT.leagues.map((b) => [b, "p_releg"]),
    cups: CUPS.map((b) => [b, "p_win"]),
  };
  const wins = X.windowsOf(), oldDocumentQuery = document.querySelectorAll;
  let totalRows = 0, totalTables = 0, totalQualifying = 0, totalResults = 0, expectedResults = 0, totalOverview = 0, titleRows = 0, survivalRows = 0, totalOmitted = 0, totalMissing = 0;
  let firstNonempty = "title";
  const valueOff = [], orderOff = [], countOff = [], resultOff = [], overviewOff = [], eloOff = [], survivalOff = [];
  for (const w of wins.length ? wins : [null]) {
    if (w) X.DWIN = w.key;
    const prev = X.snapAt(w);
    if (prev < 0) {
      console.log(`  skip    movers ${w ? w.key : "previous snapshot"} (no earlier snapshot)`);
      continue;
    }
    const label = w ? w.key : "previous";
    const start = w ? w.date : ((HISTORY.meta || {})[(HISTORY.dates || [])[prev]] || {}).as_of
      || (HISTORY.dates || [])[prev];
    const played = GWD ? Object.entries({...GWD.leagues, ...(GWD.phases || {})})
      .flatMap(([comp, g]) => (g.fixtures || []).filter((f) => Array.isArray(f.result)
        && f.kickoff.slice(0, 10) > start && f.kickoff.slice(0, 10) <= RESULT.as_of)
        .map((f) => ({...f, comp}))) : [];
    // Fill the actual Overview delta cells through the same DOM entry point a browser uses.
    // A cup Overview trims eliminated sides, so their synthetic cell additionally proves the
    // shared delta behaviour rather than silently dropping the biggest negative cup movers.
    const overview = new Map();
    for (const [b] of [...specs.title, ...specs.cups]) {
      const html = RESULT.leagues.includes(b) ? X.league(b) : RESULT.uefa.includes(b) ? X.uefa(b) : X.cup(b);
      for (const m of html.matchAll(/<td\b([^>]*data-mv-metric="p_win"[^>]*)>/g)) {
        const a = attrsOf(m[1]);
        const node = {dataset: {mvComp: a["data-mv-comp"], mvTeam: a["data-mv-team"], mvMetric: "p_win"}, textContent: ""};
        overview.set(`${a["data-mv-comp"]}|${a["data-mv-team"]}`, node);
      }
    }
    document.querySelectorAll = (selector) => selector === "#view td.mv[data-mv-metric]" ? [...overview.values()] : [];
    X.fillMovers();
    document.querySelectorAll = oldDocumentQuery;
    for (const [key, blocks] of Object.entries(specs)) {
      X.MOVERSEL = key;
      const markup = X.moversHtml(), tables = tablesOf(markup);
      totalTables += tables.length;
      const controls = [...markup.matchAll(/<button\b([^>]*data-opt="movers"[^>]*)>([\s\S]*?)<\/button>/g)], pills = controls.map((m) => attrsOf(m[1]));
      if (tables.length !== 1 || pills.length !== 4 || JSON.stringify(pills.map((p) => p["data-val"])) !== JSON.stringify(["title","europe","survival","cups"])
        || JSON.stringify(controls.map((m) => textOf(m[2]))) !== JSON.stringify(["Title race","Europe","Survival","Cups"])
        || pills.filter((p) => p["aria-pressed"] === "true").length !== 1
        || pills.find((p) => p["aria-pressed"] === "true")?.["data-val"] !== key) countOff.push(`${label} ${key}: selected table/pills differ`);
      const table = tables.find((t) => t.attr["data-movers"] === key);
      if (!table) { countOff.push(`${label} ${key}: missing table`); continue; }
      const expected = [], rows = rowsIn(table);
      let omitted = 0, missing = 0;
      for (const [b, metric] of blocks) for (const t of b.teams) {
        const was = (((HISTORY.competitions || {})[b.competition] || {})[t.team] || {})[metric]?.[prev];
        const now = t[metric];
        if (was == null || now == null) { missing++; continue; }
        const delta = 100 * (now - was);
        if (Math.abs(delta) < 0.05) { omitted++; continue; }
        expected.push({comp: b.competition, team: t.team, metric, was, now, delta});
      }
      expected.sort((a, b) => Math.abs(b.delta) - Math.abs(a.delta)
        || X.COMP_ORDER.indexOf(a.comp) - X.COMP_ORDER.indexOf(b.comp) || a.team.localeCompare(b.team));
      if (!totalRows && rows.length) firstNonempty = key;
      totalRows += rows.length; totalQualifying += expected.length; totalOmitted += omitted; totalMissing += missing;
      const shown = Math.min(50, expected.length);
      if (+table.attr["data-omitted"] !== omitted || +table.attr["data-missing"] !== missing || rows.length !== shown
        || +table.attr["data-shown"] !== shown || +table.attr["data-qualifying"] !== expected.length) {
        countOff.push(`${label} ${key}: shown/qualifying/omitted/missing ${rows.length}/${table.attr["data-qualifying"]}/${table.attr["data-omitted"]}/${table.attr["data-missing"]}, want ${shown}/${expected.length}/${omitted}/${missing}`);
      }
      const heads = (table.body.match(/<th\b/g) || []).length;
      if (rows.some((r) => r.cells.length !== heads)) countOff.push(`${label} ${key}: rows not square`);
      rows.forEach((r, i) => {
        const e = expected.find((v) => v.comp === r.attr["data-comp"] && v.team === r.team && v.metric === r.attr["data-metric"]);
        const tag = `${label} ${key} ${r.attr["data-comp"]} ${r.team}`;
        if (!e || !r.then || !r.now || !r.delta || !r.elo || !r.results) { valueOff.push(`${tag}: unexpected/incomplete row`); return; }
        const wantOrder = expected[i];
        if (key === "title") titleRows++;
        if (key === "survival") {
          survivalRows++;
          const color = e.delta > 0 ? "down" : "up";
          if (!(r.delta.attr.class || "").split(/\s+/).includes(color)) survivalOff.push(`${tag}: ${e.delta.toFixed(2)}pp should be ${color}`);
        }
        if (wantOrder && (e.comp !== wantOrder.comp || e.team !== wantOrder.team || e.metric !== wantOrder.metric)) orderOff.push(`${tag}: row ${i + 1}`);
        if (Math.abs(numberOf(r.then.html) - 100 * e.was) > 0.05 + 1e-8
          || Math.abs(numberOf(r.now.html) - 100 * e.now) > 0.05 + 1e-8
          || Math.abs(numberOf(r.delta.html) - e.delta) > 0.05 + 1e-8
          || Math.abs(e.delta) < 0.05) valueOff.push(`${tag}: then/now/delta differs from snapshots`);
        if (e.metric === "p_win" && overview.has(`${e.comp}|${e.team}`)) {
          totalOverview++;
          if (textOf(r.delta.html) !== overview.get(`${e.comp}|${e.team}`).textContent) overviewOff.push(`${tag}: delta differs from Overview`);
        }
        const rating = X.ratingIdx()[e.team], past = w && rating && (rating.past ? rating.past[w.key]
          : w.key === "season" && rating.elo0 != null ? [rating.elo0] : null);
        const elo = numberOf(r.elo.html);
        if (past ? elo == null || Math.abs(elo - (rating.elo - past[0])) > 0.05 + 1e-8 : elo != null) eloOff.push(`${tag}: Elo does not read ratings.past`);
        const actual = [...r.results.html.matchAll(/<span\b([^>]*\bdata-mover-result="[^"]*"[^>]*)>([\s\S]*?)<\/span>/g)]
          .map((m) => ({attr: attrsOf(m[1]), text: textOf(m[2])}));
        const mine = played.filter((f) => f.home === e.team || f.away === e.team);
        totalResults += actual.length; expectedResults += mine.length;
        const identity = (f) => `${f.comp}|${f.home}|${f.away}|${f.kickoff}`;
        const shown = actual.map((v) => `${v.attr["data-result-comp"]}|${v.attr["data-home"]}|${v.attr["data-away"]}|${v.attr["data-mover-result"]}`);
        if (actual.length !== mine.length || new Set(shown).size !== shown.length || mine.some((f) => !shown.includes(identity(f)))) resultOff.push(`${tag}: played-result membership`);
        for (const a of actual) {
          const f = mine.find((v) => identity(v) === `${a.attr["data-result-comp"]}|${a.attr["data-home"]}|${a.attr["data-away"]}|${a.attr["data-mover-result"]}`);
          if (!f) continue;
          const home = f.home === e.team, gf = f.result[home ? 0 : 1], ga = f.result[home ? 1 : 0];
          const want = `${gf > ga ? "W" : gf < ga ? "L" : "D"} ${gf}–${ga} ${home ? "v" : "at"} ${X.shortName(home ? f.away : f.home)}`;
          if (a.text !== want) resultOff.push(`${tag}: ${a.text} instead of ${want}`);
        }
      });
    }
  }
  X.DWIN = "1w"; X.MOVERSEL = firstNonempty;
  if (totalTables || countOff.length) check(!orderOff.length && !countOff.length, `movers: ${totalTables} category/window tables, ${totalRows} of ${totalQualifying} qualifying rows in exact absolute-change order, first50 at most; ${totalOmitted} below 0.05pp and ${totalMissing} missing counted before the cap`, [...orderOff, ...countOff].slice(0, 4).join("; "));
  if (totalRows) {
    check(!valueOff.length && !overviewOff.length && totalOverview >= titleRows, `movers: ${totalRows} rows equal their snapshots; ${totalOverview} title/Win deltas equal the Overview`, [...valueOff, ...overviewOff].slice(0, 4).join("; "));
    check(!eloOff.length, `movers: ${totalRows} Elo changes read the shared window, or say unavailable`, eloOff.slice(0, 4).join("; "));
    if (survivalRows) check(!survivalOff.length, `movers: ${survivalRows} survival rows colour rising REL red and falling REL green`, survivalOff.slice(0, 4).join("; "));
    else console.log("  skip    movers survival colours (no displayed survival changes)");
    if (GWD && expectedResults) check(totalResults > 0 && !resultOff.length, `movers: ${totalResults} played results inside the window, exactly once per shown side, with away scores reversed`, resultOff.slice(0, 4).join("; "));
    else console.log(`  skip    movers result identities (${GWD ? "no played fixture for a shown side inside these windows" : "snapshot has no gw.json"})`);
  } else console.log("  skip    movers identities (no earlier snapshot with a displayed change)");
  // Deliberately place one away result at the cutoff's final minute, another on the window's
  // start day, and another tomorrow. Date-only cutoffs include the whole final day, and the
  // start day's results were already seen by the old ratings fit.
  const w = wins[0];
  if (w && X.snapAt(w) >= 0) {
    X.DWIN = w.key;
    const table = tablesOf(X.moversHtml()).find((t) => rowsIn(t).length);
    const row = table && rowsIn(table)[0];
    if (row) {
      const team = row.team, comp = row.attr["data-comp"], other = "Movers boundary opponent";
      const tomorrow = new Date(Date.parse(RESULT.as_of + "T00:00:00Z") + 86400000).toISOString().slice(0, 10);
      const fixtures = [w.date + " 23:59:00", RESULT.as_of + " 23:59:00", tomorrow + " 00:00:00"]
        .map((kickoff) => ({kickoff, home: other, away: team, result: [4, 1]}));
      X.GW = {leagues: {[comp]: {teams: [team, other], fixtures}}, phases: {}};
      const actual = rowsIn(tablesOf(X.moversHtml()).find((t) => t.attr["data-movers"] === table.attr["data-movers"]))
        .find((r) => r.team === team && r.attr["data-comp"] === comp);
      const results = [...actual.results.html.matchAll(/<span\b([^>]*\bdata-mover-result="[^"]*"[^>]*)>([\s\S]*?)<\/span>/g)]
        .map((m) => ({attr: attrsOf(m[1]), text: textOf(m[2])}));
      check(results.length === 1 && results[0].attr["data-mover-result"] === fixtures[1].kickoff
        && results[0].text === `L 1–4 at ${X.shortName(other)}`,
      "movers: 3 boundary fixtures exclude the start day and future, include the cutoff's final minute, reverse an away loss",
      results.map((r) => `${r.attr["data-mover-result"]} ${r.text}`).join("; "));
    } else console.log("  skip    movers result boundaries (no displayed changes)");
  }
  X.GW = null;
  const noResults = X.moversHtml();
  X.HISTORY = {...HISTORY, dates: [RESULT.source?.date || RESULT.as_of]};
  const oneSnapshot = X.moversHtml();
  X.HISTORY = HISTORY; X.GW = GWD; X.DWIN = "1w"; X.MOVERSEL = "title";
  check((!totalRows || noResults.includes("Results unavailable in this snapshot"))
    && !noResults.includes("data-mover-result=") && oneSnapshot.includes("changes need an earlier snapshot"),
  "movers: 2 older-data fallbacks keep missing results explicit and one snapshot has no invented baseline");
  // A deliberately crowded miniature snapshot exercises all categories, all four windows,
  // ties in absolute change, both change signs, and exclusions that must be counted before cap.
  const syntheticWindows=[{key:"1w",label:"1 week",date:"2026-10-13"},{key:"1m",label:"1 month",date:"2026-09-20"},{key:"3m",label:"3 months",date:"2026-07-20"},{key:"season",label:"season",date:"2026-08-01"}];
  const syntheticDates=["2026-07-20","2026-08-01","2026-09-20","2026-10-13","2026-10-21"];
  const syntheticHistory={dates:syntheticDates,meta:Object.fromEntries(syntheticDates.map((day)=>[day,{as_of:day==="2026-10-21"?"2026-10-20":day,version:11,model:"movers-test"}])),competitions:{}};
  const makeBlock=(competition,from,n)=>({competition,teams:Array.from({length:n},(_,at)=>{
    const i=from+at,type=i%80,team=`Synthetic ${String(199-i).padStart(3,"0")}`,now=.3+(i%5)*.01;
    const row={team};
    const old={};
    for(const metric of ["p_win","p_ucl","p_top8","p_releg"]) {
      row[metric]=type>=76?null:now;
      old[metric]=Array.from({length:4},(_,w)=>type>=72&&type<76?null:now-(type>=64&&type<72?.0003:((i+w)%2?-1:1)*(1+(i*3+w)%13)*.001));
      old[metric].push(row[metric]);
    }
    (syntheticHistory.competitions[competition] ||= {})[team]=old;
    return row;
  })});
  const synthetic={...RESULT,as_of:"2026-10-20",source:{kind:"snapshot",date:"2026-10-21"},model:"movers-test",ratings:{windows:syntheticWindows,teams:[]},
    leagues:[makeBlock("English Premier League",0,20),makeBlock("Spanish La Liga",20,20),makeBlock("Italian Serie A",40,20),makeBlock("German Bundesliga",60,20)],
    uefa:[makeBlock("UEFA Champions League",80,20)],cups:[makeBlock("English FA Cup",0,40),makeBlock("German DFB Pokal",40,40)]};
  const syntheticSpecs={title:[...synthetic.leagues,...synthetic.uefa].map((b)=>[b,"p_win"]),europe:[...synthetic.leagues.map((b)=>[b,"p_ucl"]),...synthetic.uefa.map((b)=>[b,"p_top8"])],survival:synthetic.leagues.map((b)=>[b,"p_releg"]),cups:synthetic.cups.map((b)=>[b,"p_win"])};
  X.RESULT=synthetic;X.HISTORY=syntheticHistory;X.GW=null;
  const capOff=[],accountOff=[];let crowdedTables=0,crowdedRows=0,crowdedQualifying=0,crowdedBelow=0,crowdedMissing=0;
  for(const w of syntheticWindows) for(const [category,blocks] of Object.entries(syntheticSpecs)) {
    X.DWIN=w.key;X.MOVERSEL=category;
    const prev=syntheticDates.indexOf(w.date),expected=[];let omitted=0,missing=0;
    for(const [b,metric] of blocks) for(const t of b.teams) {
      const was=syntheticHistory.competitions[b.competition][t.team][metric][prev],now=t[metric];
      if(was==null||now==null){missing++;continue;}
      const delta=100*(now-was);if(Math.abs(delta)<.05){omitted++;continue;}
      expected.push({comp:b.competition,team:t.team,metric,was,now,delta});
    }
    expected.sort((a,b)=>Math.abs(b.delta)-Math.abs(a.delta)||X.COMP_ORDER.indexOf(a.comp)-X.COMP_ORDER.indexOf(b.comp)||a.team.localeCompare(b.team));
    const html=X.moversHtml(),tables=tablesOf(html),table=tables[0],rows=table?rowsIn(table):[],data=X.moversData(category),tag=`${w.key}/${category}`;
    crowdedTables++;crowdedRows+=rows.length;crowdedQualifying+=expected.length;crowdedBelow+=omitted;crowdedMissing+=missing;
    if(expected.length<=50||tables.length!==1||table?.attr["data-movers"]!==category||rows.length!==50||data.rows.length!==expected.length||data.shown.length!==50)capOff.push(`${tag}: expected first50 of${expected.length}, got${rows.length}`);
    rows.forEach((row,i)=>{
      const e=expected[i];if(!e||row.attr["data-comp"]!==e.comp||row.team!==e.team||row.attr["data-metric"]!==e.metric||Math.abs(numberOf(row.then.html)-100*e.was)>.05+1e-9||Math.abs(numberOf(row.now.html)-100*e.now)>.05+1e-9||Math.abs(numberOf(row.delta.html)-e.delta)>.05+1e-9)capOff.push(`${tag}: row${i+1} is not the exact ordered prefix`);
    });
    if(+table?.attr["data-qualifying"]!==expected.length||+table?.attr["data-shown"]!==50||+table?.attr["data-omitted"]!==omitted||+table?.attr["data-missing"]!==missing||data.qualifying!==expected.length||data.omitted!==omitted||data.missing!==missing||!textOf(html).replace(/\s+/g," ").includes(`50 of ${expected.length}`))accountOff.push(`${tag}: full populations or displayed/total text differ`);
  }
  check(crowdedTables===16&&crowdedRows===800&&!capOff.length,`movers cap: ${crowdedTables} synthetic category/window tables show exactly800 first50 rows from${crowdedQualifying} qualifying changes, preserving values and total tie order`,capOff.slice(0,4).join("; "));
  check(crowdedBelow>0&&crowdedMissing>0&&!accountOff.length,`movers accounting: ${crowdedQualifying} qualifying /${crowdedBelow} below-precision /${crowdedMissing} missing changes counted before capping; all16 tables state shown versus full total`,accountOff.slice(0,4).join("; "));
  X.RESULT=RESULT;X.HISTORY=HISTORY;X.GW=GWD;X.DWIN="1w";X.MOVERSEL="title";

  const models = [[{version: 10}, "2026-08-22", "2026-10-21"],
    [{version: 4}, "2026-10-09", "2026-10-21"], [{}, "2026-09-20", "before 2026-10-21"],
    [{model: "future-model", version: 11}, "2026-10-21", "future-model"]];
  check(models.every(([p, day, model]) => X.modelName(p, day) === model),
    `movers: ${models.length} model stamps distinguish backfilled August, legacy v4, older fits and explicit generations`);
}

// ---------------------------------------------------------------- full team pages
// The page assembles existing views: its summary, fixtures, run-in cells and conditional stakes
// must be the same numbers as those views. Extra played fixtures independently fill cup history.
{
  X.GW = GWD; X.RESULT = RESULT; X.HISTORY = HISTORY;
  const decode = (s) => s.replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">").replace(/&amp;/g, "&");
  const text = (s) => decode(s.replace(/<[^>]*>/g, "")).trim();
  const attr = (s) => Object.fromEntries([...s.matchAll(/([\w-]+)="([^"]*)"/g)].map((m) => [m[1], decode(m[2])]));
  const td = (s) => [...s.matchAll(/<td\b([^>]*)>([\s\S]*?)<\/td>/g)].map((m) => ({attr: attr(m[1]), text: text(m[2]), html: m[0]}));
  const key = (f) => [f.competition, f.home, f.away, f.kickoff.slice(0, 10)].join("|");
  const equal = (a, b) => a == null || b == null ? a == null && b == null : Math.abs(a - b) < 1e-10;
  const names = Object.keys(TEAMD).length ? Object.keys(TEAMD) : [RESULT.leagues[0].teams[0].team];
  const summaryOff = [], fixtureOff = [], runInOff = [], historyOff = [], formOff = [], stakeOff = [];
  let summaryValues = 0, fixtureRows = 0, extraCupRows = 0, runInCells = 0, historyLines = 0, historyCells = 0, formCells = 0, singleFormMarkers = 0, stakeCells = 0, awayStakeCells = 0;
  const checkSeries = (html, id, expected, tag) => {
    const wanted = new Map([...expected].filter(([, values]) => values.some((v) => v != null)));
    const chart = X.LC[id];
    if (!wanted.size) {
      if (chart) historyOff.push(`${tag}: chart without values`);
      return;
    }
    const svg = html.match(new RegExp(`<svg id="${id}"[\\s\\S]*?<\\/svg>`));
    const lines = svg ? (svg[0].match(/stroke-width="2\.25"/g) || []).length + (svg[0].match(/data-hl=/g) || []).length : 0;
    if (!chart || chart.vals.size !== wanted.size || lines !== wanted.size) { historyOff.push(`${tag}: ${lines} lines instead of ${wanted.size}`); return; }
    historyLines += wanted.size;
    for (const [name, values] of wanted) {
      const got = chart.vals.get(name);
      if (!got || got.length !== values.length) { historyOff.push(`${tag} ${name}: wrong number of dates`); continue; }
      values.forEach((v, i) => { historyCells++; if (!equal(got[i], v)) historyOff.push(`${tag} ${name} at ${i}: not its snapshot value`); });
    }
  };
  const independentFixtures = (team, extras) => {
    const rows = new Map();
    const add = (raw, g, comp, kind, source) => {
      if (raw.home !== team && raw.away !== team || raw.result && raw.kickoff.slice(0, 10) > RESULT.as_of || !raw.result && !raw.ladder) return;
      const f = {...raw, competition: comp, kind};
      if (!rows.has(key(f))) rows.set(key(f), {f, g: g || {teams: [f.home, f.away]}, keys: f.stakes_of || g?.stakes_of || X.STAKES_OF[kind] || [], source});
    };
    for (const [blocks, kind] of [[GWD?.leagues, "league"], [GWD?.phases, "uefa"]]) for (const [comp, g] of Object.entries(blocks || {}))
      for (const f of g.fixtures || []) add(f, g, comp, kind, "snapshot");
    for (const f of MATCHES.fixtures || []) if (!f.result) add(f, (f.kind === "league" ? GWD?.leagues : GWD?.phases)?.[f.competition], f.competition, f.kind, "forecast");
    for (const f of extras) if (f.result) add(f, null, f.competition, f.kind, "history");
    return rows;
  };
  const testStakes = (team, entries, html, tag) => {
    const next = entries.find(({f}) => !f.result && f.kickoff.slice(0, 10) > RESULT.as_of);
    if (!next) return;
    const home = next.f.home === team, stored = next.f.stakes?.[home ? 0 : 1];
    const rows = [...html.matchAll(/<tr\b([^>]*data-team-stake="[^"]+"[^>]*)>([\s\S]*?)<\/tr>/g)];
    if (!stored) { if (rows.length) stakeOff.push(`${tag}: invented stakes`); return; }
    if (rows.length !== Math.min(stored.length, next.keys.length)) stakeOff.push(`${tag}: incomplete fate table`);
    rows.forEach((row) => {
      const a = attr(row[1]), i = next.keys.indexOf(a["data-team-stake"]), raw = stored[i];
      if (i < 0) { stakeOff.push(`${tag}: unknown fate`); return; }
      const values = Array.isArray(raw) ? raw.slice() : [raw, raw, raw];
      if (!home) values.reverse();
      const c = td(row[2]), exact = (a["data-team-wdl"] || "").split("|").map((v) => v === "" ? null : +v);
      values.forEach((v, k) => {
        stakeCells++; if (!home) awayStakeCells++;
        const rendered = c[k + 1].text === "—" ? null : parseFloat(c[k + 1].text) / 100;
        if (!equal(v, exact[k]) || (v == null ? rendered != null : rendered == null || Math.abs(v - rendered) > .0005 + 1e-9)) stakeOff.push(`${tag} ${a["data-team-stake"]} ${k}: wrong orientation/value`);
      });
    });
  };
  for (const team of names) {
    X.TEAM_HCOMP = ""; X.TEAM_TREND = "chance"; X.TEAM_RATING = "elo"; X.VIZOPT.rim = "win";
    for (const id of ["lcteamoutlook", "lcteamratings", "lcteamform"]) delete X.LC[id];
    const extras = TEAMD[team] || [], html = X.teamPageHtml(team, extras), expected = independentFixtures(team, extras);
    const blocks = [...html.matchAll(/<div class="comp" data-comp="([^"]*)">/g)];
    for (let i = 0; i < blocks.length; i++) {
      const comp = decode(blocks[i][1]), chunk = html.slice(blocks[i].index, blocks[i + 1]?.index || html.indexOf('<div class="panel"'));
      const block = [...RESULT.leagues, ...RESULT.uefa].find((b) => b.competition === comp);
      if (block) {
        const raw = block.teams.find((t) => t.team === team), shown = chunk.match(/<span>XPTS<\/span><b>([^<]*)<\/b>/);
        if (raw?.mean_pts == null) {
          console.log(`  skip    team page ${team}, ${comp}: XPTS identity (snapshot has no mean_pts)`);
          if (shown && shown[1] !== "—") summaryOff.push(`${team} ${comp}: invented XPTS without a payload value`);
          continue;
        }
        const overview = RESULT.leagues.includes(block) ? X.league(block) : X.uefa(block);
        const heads = [...(overview.match(/<thead>([\s\S]*?)<\/thead>/) || [, ""])[1].matchAll(/<th\b[^>]*>([\s\S]*?)<\/th>/g)].map((m) => text(m[1]));
        const row = [...overview.matchAll(/<tr\b[^>]*>([\s\S]*?)<\/tr>/g)].map((m) => td(m[1])).find((c) => c.some(cell => cell.attr["data-team"] === team));
        summaryValues++;
        if (!shown || !raw || Math.abs(+shown[1] - raw.mean_pts) > .05 + 1e-9 || row && shown[1] !== row[heads.indexOf("XPTS")]?.text) summaryOff.push(`${team} ${comp}: XPTS differs from Overview`);
      }
      if (comp === "Ratings") {
        const raw = X.ratingIdx()[team], shown = chunk.match(/<span>Elo<\/span><b>([^<]*)<\/b>/);
        summaryValues++;
        if (!shown || !raw || parseFloat(shown[1]) !== Math.round(raw.elo)) summaryOff.push(`${team}: Elo differs from Ratings`);
      }
    }
    const rendered = [...html.matchAll(/<tr\b([^>]*data-team-fixture="[^"]+"[^>]*)>([\s\S]*?)<\/tr>/g)];
    const seen = new Set();
    if (rendered.length !== expected.size) fixtureOff.push(`${team}: ${rendered.length} fixtures instead of ${expected.size}`);
    for (const row of rendered) {
      const a = attr(row[1]), k = a["data-team-fixture"], want = expected.get(k), cells = td(row[2]); fixtureRows++;
      if (!want || seen.has(k)) { fixtureOff.push(`${team}: unexpected/duplicate ${k}`); continue; }
      seen.add(k);
      const source = td(X.fixtureRow(want.g, want.f, want.keys));
      if (cells.slice(2).map((c) => c.html).join("") !== source.map((c) => c.html).join("") || a["data-team-fixture-source"] !== want.source) fixtureOff.push(`${team} ${k}: differs from Fixtures row`);
      const score = want.f.result, mine = score && (want.f.home === team ? score : score.slice().reverse());
      if (cells[1].text !== (mine ? mine[0] > mine[1] ? "W" : mine[0] < mine[1] ? "L" : "D" : "—")) fixtureOff.push(`${team} ${k}: wrong W/D/L`);
      if (want.f.result && want.f.kind === "cup" && extras.some((f) => key(f) === k)) extraCupRows++;
    }
    const entries = X.teamFixtures(team, extras);
    testStakes(team, entries, html, `${team} next match`);
    const away = entries.find((r) => !r.f.result && r.f.away === team && r.f.stakes);
    if (away) testStakes(team, [away], X.teamNextStakes(team, [away]), `${team} away match`);
    for (const mode of ["win", "pts"]) {
      X.VIZOPT.rim = mode;
      const actual = X.teamRunIn(team), wanted = [];
      for (const [blocks, collection, kind] of [[RESULT.leagues, GWD?.leagues, "league"], [RESULT.uefa, GWD?.phases, "uefa"]]) for (const block of blocks) {
        const g = collection?.[block.competition];
        if (!g || !block.teams.some((r) => r.team === team)) continue;
        for (const cell of X.vizRI(block, kind, g).matchAll(/<td\b[^>]*data-ri="([^"]*)"[^>]*>[\s\S]*?<\/td>/g)) if (decode(cell[1]).split("|")[0] === team) wanted.push(cell[0]);
      }
      const got = [...actual.matchAll(/<td\b[^>]*data-ri="[^"]*"[^>]*>[\s\S]*?<\/td>/g)].map((m) => m[0]);
      runInCells += got.length;
      if (JSON.stringify(got) !== JSON.stringify(wanted)) runInOff.push(`${team} ${mode}: differs from the run-in chart`);
    }
    const indices = (HISTORY.dates || []).map((date, i) => ({date, i})).filter(({date}) => date <= (RESULT.source?.date || RESULT.as_of)
      && ((HISTORY.meta || {})[date]?.as_of || date) <= RESULT.as_of).map(({i}) => i);
    const select = (values, scale = 1) => indices.map((i) => values?.[i] == null ? null : values[i] * scale);
    const data = X.teamHistoryData(team);
    if (JSON.stringify(data.dates) !== JSON.stringify(indices.map((i) => HISTORY.dates[i]))) historyOff.push(`${team}: history date clipping`);
    if (indices.length >= 2) for (const block of [...RESULT.leagues, ...RESULT.uefa, ...CUPS].filter((b) => b.teams.some((r) => r.team === team))) {
      const s = HISTORY.competitions?.[block.competition]?.[team] || {};
      const metrics = RESULT.leagues.includes(block) ? [["p_win", "Title"], ["p_ucl", "UCL"], ["p_releg", "REL"]]
        : RESULT.uefa.includes(block) ? [["p_win", "Win"], ["p_top8", "Top 8"]] : [["p_win", "Win"]];
      for (const trend of ["chance", ...(s.mean_pts?.some((v) => v != null) ? ["points"] : [])]) {
        X.TEAM_HCOMP = block.competition; X.TEAM_TREND = trend;
        delete X.LC.lcteamoutlook; delete X.LC.lcteamratings;
        const part = X.teamHistoryCharts(team), values = trend === "points" ? new Map([["XPTS", select(s.mean_pts)]])
          : new Map(metrics.map(([key, name]) => [name, select(s[key], 100)]));
        checkSeries(part, "lcteamoutlook", values, `${team} ${block.competition} ${trend}`);
      }
    }
    if (indices.length >= 2) for (const rating of ["elo", "strength"]) {
      X.TEAM_RATING = rating; delete X.LC.lcteamratings;
      const part = X.teamHistoryCharts(team), r = HISTORY.ratings?.[team] || {};
      const values = new Map((rating === "elo" ? [["elo", "Elo"]] : [["att", "ATT"], ["def", "DEF"]]).map(([key, name]) => [name, select(r[key])]));
      checkSeries(part, "lcteamratings", values, `${team} ${rating}`);
    }
    const form=X.teamFormData(team,entries),actual=entries.filter(({f})=>Array.isArray(f.result)&&f.result.length===2).slice().sort((a,b)=>Workspace.fixtureInstant(a.f.kickoff,a.f.competition)-Workspace.fixtureInstant(b.f.kickoff,b.f.competition)||key(a.f).localeCompare(key(b.f)));
    if(form.length!==actual.length)formOff.push(`${team}: wrong actual match count`);
    actual.forEach(({f},i)=>{
      const last=actual.slice(Math.max(0,i-4),i+1),known=last.filter(({f})=>f.xg?.length===2&&f.xg.every(v=>Number.isFinite(v)&&v>=0));
      const values=[0,1].map(side=>known.length===last.length?last.reduce((sum,{f})=>sum+f.xg[f.home===team?side:1-side],0)/last.length:null);
      formCells+=2;
      if(!form[i]||!equal(form[i].for,values[0])||!equal(form[i].against,values[1])||form[i].known!==known.length||JSON.stringify(form[i].window)!==JSON.stringify(last.map(({f})=>key(f))))formOff.push(`${team}: form at ${i} not its exact actual last5 population`);
    });
    if(actual.length===1&&form[0].for!==null) {
      const svg = html.match(/<svg id="lcteamform"[\s\S]*?<\/svg>/)?.[0] || "";
      const markers = [...svg.matchAll(/<circle\b([^>]*data-line-single="[^"]+"[^>]*)\/?\s*>/g)].map((m) => attr(m[1]));
      singleFormMarkers += markers.length;
      const chart = X.LC.lcteamform;
      if (markers.length !== 2 || !chart || ["xG for", "xG against"].some((name) => {
        const marker = markers.find((m) => m["data-line-single"] === name), value = chart?.vals.get(name)?.[0];
        return !marker || !(+marker.r > 0) || !Number.isFinite(+marker.cx) || !Number.isFinite(+marker.cy)
          || Math.abs(+marker.cx - chart.X(0)) > .05 || Math.abs(+marker.cy - chart.Y(value)) > .05;
      })) formOff.push(`${team}: its two one-match form series need visible markers at their values`);
    }
    if ((HISTORY.dates || []).length > 3) {
      const old = HISTORY.dates[Math.floor(HISTORY.dates.length / 2)], cutoff = HISTORY.meta?.[old]?.as_of || old;
      X.RESULT = {...RESULT, source: {kind: "snapshot", date: old}, as_of: cutoff};
      const clipped = X.teamHistoryData(team);
      const oldIndices = HISTORY.dates.map((date, i) => ({date, i})).filter(({date}) => date <= old
        && (HISTORY.meta?.[date]?.as_of || date) <= cutoff).map(({i}) => i);
      const oldSelect = (v, scale = 1) => oldIndices.map((i) => v?.[i] == null ? null : scale * v[i]);
      let valuesWrong = JSON.stringify(clipped.indices) !== JSON.stringify(oldIndices);
      for (const [metric, values] of clipped.ratings) if (JSON.stringify(values) !== JSON.stringify(oldSelect(HISTORY.ratings?.[team]?.[metric]))) valuesWrong = true;
      for (const b of clipped.byComp) {
        const source = HISTORY.competitions?.[b.competition]?.[team] || {};
        for (const [name, values] of b.chance) {
          const metric = {Title: "p_win", Win: "p_win", UCL: "p_ucl", REL: "p_releg", "Top 8": "p_top8"}[name];
          if (JSON.stringify(values) !== JSON.stringify(oldSelect(source[metric], 100))) valuesWrong = true;
        }
        for (const [, values] of b.points) if (JSON.stringify(values) !== JSON.stringify(oldSelect(source.mean_pts))) valuesWrong = true;
      }
      if (clipped.dates.some((d) => d > old || (HISTORY.meta?.[d]?.as_of || d) > cutoff)
        || valuesWrong) historyOff.push(`${team}: older snapshot leaks or shifts later history`);
      X.RESULT = RESULT;
    }
  }
  X.VIZOPT.rim = "win"; X.TEAM_HCOMP = ""; X.TEAM_TREND = "chance"; X.TEAM_RATING = "elo";
  check(summaryValues > 0 && !summaryOff.length, `team page: ${names.length} sides, ${summaryValues} XPTS/Elo summary values equal Overview/Ratings`, summaryOff.slice(0, 4).join("; "));
  check(fixtureRows > 0 && !fixtureOff.length, `team page: ${fixtureRows} match rows equal Fixtures, one per fixture, W/D/L from the side's view`, fixtureOff.slice(0, 4).join("; "));
  if (Object.keys(TEAMD).length) check(extraCupRows > 0, `team page: ${extraCupRows} played cup matches from the team endpoint survive the merge`);
  else console.log("  skip    team page played-cup coverage (no team-fixtures.json passed)");
  if (GWD) check(runInCells > 0 && !runInOff.length, `team page: ${runInCells} run-in cells equal the shared chart in win-chance and expected-points modes`, runInOff.slice(0, 4).join("; "));
  else console.log("  skip    team page run-in identity (no gw.json)");
  if (historyLines) check(historyCells > 0 && !historyOff.length, `team page: ${historyLines} history lines, ${historyCells} values equal their snapshots; older dates clip future values`, historyOff.slice(0, 4).join("; "));
  else console.log("  skip    team page history lines (fewer than two snapshots or no series)");
  if (formCells) check(!formOff.length, `team page: ${formCells} xG form values equal the last five matches; ${singleFormMarkers} one-match series have visible markers`, formOff.slice(0, 4).join("; "));
  else console.log("  skip    team page form identity (no played xG)");
  if (stakeCells) check(awayStakeCells > 0 && !stakeOff.length, `team page: ${stakeCells} next-match fate values equal the fixture's stakes, including ${awayStakeCells} away values reversed`, stakeOff.slice(0, 4).join("; "));
  else console.log("  skip    team page full-stakes identity (snapshot has no stakes)");
  const unresolved = Object.entries({...GWD?.leagues, ...GWD?.phases}).flatMap(([comp, g]) => (g.fixtures || [])
    .filter((f) => !f.result && f.kickoff.slice(0, 10) <= RESULT.as_of).map((f) => ({...f, competition: comp})));
  const unresolvedOff = [];
  let nextSides = 0;
  for (const f of unresolved) for (const team of [f.home, f.away]) {
    const entries = X.teamFixtures(team), future = entries.find(({f}) => !f.result && f.kickoff.slice(0, 10) > RESULT.as_of);
    const html = X.teamNextStakes(team, entries), shown = html.match(/data-team-next="([^"]*)"/);
    const modelNext = Object.entries(NEXT).flatMap(([competition, sides]) => {
      const n = sides[team];
      return n && n.kickoff.slice(0, 10) > RESULT.as_of ? [{competition, kickoff: n.kickoff,
        home: n.isHome ? team : n.opponent, away: n.isHome ? n.opponent : team}] : [];
    }).sort((a, b) => a.kickoff.localeCompare(b.kickoff) || X.COMP_ORDER.indexOf(a.competition) - X.COMP_ORDER.indexOf(b.competition))[0];
    nextSides++;
    if (!entries.some((e) => key(e.f) === key(f)) || (future ? !shown || decode(shown[1]) !== key(future.f) : shown)
      || modelNext && (!shown || decode(shown[1]) !== key(modelNext))) unresolvedOff.push(`${team}: stale unresolved fixture selected or removed`);
  }
  if (nextSides) check(!unresolvedOff.length, `team page: ${nextSides} sides retain unresolved past fixtures but select the model's future next match`, unresolvedOff.slice(0, 4).join("; "));
  else console.log("  skip    team page unresolved-fixture next-match identity (no unresolved fixture before the cutoff)");
  const active = new Set([...RESULT.leagues, ...RESULT.uefa, ...CUPS].flatMap((b) => b.teams.map((t) => t.team)));
  const eliminated = Object.keys(TEAMD).find((team) => !active.has(team) && TEAMD[team].some((f) => f.kind === "cup" && f.result));
  if (eliminated) {
    X.FOCUS = eliminated; X.TEAM_PAGE = true;
    X.renderTeamCard();
    const html = X.teamPageHtml(eliminated, TEAMD[eliminated]);
    const rows = [...html.matchAll(/data-team-fixture="([^"]*)"/g)];
    const played = TEAMD[eliminated].filter((f) => f.result && f.kickoff.slice(0, 10) <= RESULT.as_of);
    const fixtures = X.teamFixtures(eliminated, TEAMD[eliminated]);
    check(X.FOCUS === eliminated && X.TEAM_PAGE && mk("teamcard").innerHTML === "" && played.length > 0
      && rows.length === played.length && fixtures.every(({f}) => f.result)
      && !html.includes('data-comp="Ratings"') && !html.includes('data-team-series="lcteamratings"'),
    `team page: eliminated ${eliminated} keeps its full-page route and ${played.length} real played matches, with no invented forecast or rating`);
    X.FOCUS = null; X.TEAM_PAGE = false;
  } else console.log("  skip    team page eliminated-side route lifecycle (no eliminated side passed in team-fixtures.json)");
}

// ---------------------------------------------------------------- match cards
// Sample every imminent forecast plus a played match from every available competition. The
// card reads exactly the shared fixture values; its away fates reverse H/D/A into side W/D/L.
{
  X.RESULT = RESULT; X.GW = GWD;
  const decode = (s) => s.replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">").replace(/&amp;/g, "&");
  const plain = (s) => decode(s.replace(/<[^>]*>/g, "")).trim();
  const attrs = (s) => Object.fromEntries([...s.matchAll(/([\w-]+)="([^"]*)"/g)].map((m) => [m[1], decode(m[2])]));
  const cells = (s) => [...s.matchAll(/<td\b([^>]*)>([\s\S]*?)<\/td>/g)].map((m) => ({attr: attrs(m[1]), text: plain(m[2])}));
  const mkey = (f) => [f.home, f.away, f.kickoff.slice(0, 10)].join("|");
  const fullKey = (f) => f.competition + "|" + mkey(f);
  const number = (s) => s === "—" || s === "" ? null : parseFloat(s.replace("−", "-"));
  const equal = (a, b, tol = 1e-10) => a == null || b == null ? a == null && b == null : Math.abs(a - b) <= tol;
  const extras = Object.values(TEAMD).flat(), all = X.matchFixtures(extras);
  const selected = new Map();
  for (const f of MATCHES.fixtures || []) {
    const entry = all.find((e) => fullKey(e.f) === fullKey(f));
    if (entry) selected.set(fullKey(entry.f), entry);
  }
  for (const comp of new Set(all.map((e) => e.competition))) {
    const played = all.filter((e) => e.competition === comp && e.f.result).at(-1);
    if (played) selected.set(fullKey(played.f), played);
  }
  const valueOff = [], stakeOff = [], recentOff = [], h2hOff = [], hookOff = [];
  let cards = 0, forecasts = 0, playedCards = 0, xgValues = 0, ratingValues = 0, tops = 0, stakeValues = 0, awayValues = 0, recentRows = 0, h2hRows = 0, knownH2h = 0, missingH2h = 0;
  for (const entry of selected.values()) {
    const {f, g, keys} = entry, key = mkey(f), tag = `${entry.competition} ${key}`;
    const html = X.matchCardHtml(entry, extras), row = html.match(/<tr\b([^>]*data-match-hda="[^"]*"[^>]*)>([\s\S]*?)<\/tr>/);
    cards++; if (f.result) playedCards++; else forecasts++;
    const card = html.match(/data-match-card="([^"]*)"/), found = X.findMatch(key, extras);
    if (!card || decode(card[1]) !== key || !found || fullKey(found.f) !== fullKey(f) || !row) { valueOff.push(`${tag}: missing/wrong route or values row`); continue; }
    const a = attrs(row[1]), c = cells(row[2]), fixture = X.fixtureRow(g, f, keys), fc = cells(fixture);
    if (!fixture.includes(`data-match="${key.replace(/&/g, "&amp;").replace(/"/g, "&quot;")}"`)) hookOff.push(`${tag}: Fixture row has no match route`);
    if (f.ladder) {
      const expected = [f.ladder.h1, f.ladder.d, f.ladder.a1], stored = a["data-match-hda"].split("|").map(Number);
      expected.forEach((p, i) => { if (!equal(stored[i], p) || c[i].text !== fc[i + 4].text) valueOff.push(`${tag}: H/D/A differs from Fixtures`); });
    } else if (a["data-match-hda"] !== "" || c.slice(0, 3).some((v) => v.text !== "—")) valueOff.push(`${tag}: invented played-match forecast`);
    let xg = f.xg?.length === 2 && f.xg.every((v) => v != null && Number.isFinite(v)) ? f.xg : null;
    const hi = g.teams.indexOf(f.home);
    if (!xg && !f.result && hi >= 0 && f.round != null && g.xgf && g.xga) xg = [g.xgf[hi][f.round] - g.xgf[hi][f.round - 1], g.xga[hi][f.round] - g.xga[hi][f.round - 1]];
    const shownXg = a["data-match-xg"] === "" ? null : a["data-match-xg"].split("|").map(Number);
    if (xg) {
      xgValues += 2;
      if (!shownXg || xg.some((v, i) => !equal(v, shownXg[i])) || c[3].text !== fc[7].text) valueOff.push(`${tag}: xG differs from Fixtures`);
    } else if (shownXg || c[3].text !== "—") valueOff.push(`${tag}: invented unavailable xG`);
    const top = [...html.matchAll(/data-match-top="([^"]*)"/g)].map((m) => decode(m[1])); tops += top.length;
    if (JSON.stringify(top) !== JSON.stringify((f.top || []).map(([score, p]) => `${score}|${p}`))) valueOff.push(`${tag}: likeliest scores differ`);
    const ratings = [...html.matchAll(/<tr\b([^>]*data-match-rating="[^"]*"[^>]*)>([\s\S]*?)<\/tr>/g)];
    for (const r of ratings) {
      const team = attrs(r[1])["data-match-rating"], raw = X.ratingIdx()[team], factors = RESULT.ratings?.rel?.[entry.competition]?.now, shown = cells(r[2]);
      const expected = [raw ? Math.round(raw.elo) : null, raw && factors ? raw.att * factors[0] : null, raw && factors ? raw.def * factors[1] : null];
      ratingValues += 3;
      expected.forEach((v, i) => { if (!equal(number(shown[i + 1].text), v, i ? .005 + 1e-9 : 0)) valueOff.push(`${tag} ${team}: wrong Elo/competition-scale strength`); });
    }
    if (ratings.length !== 2) valueOff.push(`${tag}: not two rating rows`);
    const stakes = [...html.matchAll(/<tr\b([^>]*data-match-stake="[^"]*"[^>]*)>([\s\S]*?)<\/tr>/g)];
    const expectedFates = f.ladder && f.stakes ? 2 * Math.min(keys.length, f.stakes[0].length) : 0;
    if (stakes.length !== expectedFates) stakeOff.push(`${tag}: ${stakes.length} fates instead of ${expectedFates}`);
    for (const r of stakes) {
      const a = attrs(r[1]), [side, fate] = a["data-match-stake"].split("|"), i = keys.indexOf(fate), home = side === "home";
      const raw = f.stakes?.[home ? 0 : 1]?.[i], expected = Array.isArray(raw) ? raw.slice() : [raw, raw, raw];
      if (!home) expected.reverse();
      const exact = a["data-match-wdl"].split("|").map((v) => v === "" ? null : Number(v)), shown = cells(r[2]);
      expected.forEach((v, k) => {
        stakeValues++; if (!home) awayValues++;
        const displayed = shown[k + 1].text === "—" ? null : parseFloat(shown[k + 1].text) / 100;
        if (i < 0 || !equal(exact[k], v) || !equal(displayed, v, .0005 + 1e-9)) stakeOff.push(`${tag} ${side} ${fate}: W/D/L not its source stakes`);
      });
      const finite = expected.filter((v) => v != null), swing = finite.length ? 100 * (Math.max(...finite) - Math.min(...finite)) : 0;
      if (!equal(number(shown[4].text), swing, .05 + 1e-9)) stakeOff.push(`${tag} ${side} ${fate}: wrong swing`);
    }
    const recent = [...html.matchAll(/<div data-match-recent="([^"]*)">/g)];
    for (let i = 0; i < recent.length; i++) {
      const team = decode(recent[i][1]), stop = recent[i + 1]?.index || html.indexOf('<div style="margin-top:18px">', recent[i].index);
      const chunk = html.slice(recent[i].index, stop), rows = [...chunk.matchAll(/<tr\b([^>]*data-match-recent-row="[^"]*"[^>]*)>([\s\S]*?)<\/tr>/g)];
      const expected = all.filter((e) => e.competition === entry.competition && e.f.result && (e.f.home === team || e.f.away === team) && e.f.kickoff < f.kickoff)
        .sort((a, b) => b.f.kickoff.localeCompare(a.f.kickoff) || a.f.home.localeCompare(b.f.home) || a.f.away.localeCompare(b.f.away)).slice(0, 5);
      if (rows.length !== expected.length) recentOff.push(`${tag} ${team}: incomplete last five`);
      rows.forEach((r, k) => {
        recentRows++; const source = expected[k]?.f, a = attrs(r[1]), c = cells(r[2]);
        if (!source || a["data-match-recent-row"] !== mkey(source)) { recentOff.push(`${tag} ${team}: last five order/membership`); return; }
        const home = source.home === team, score = home ? source.result : source.result.slice().reverse();
        const ending = source.outcome === "afterextratime" ? " AET" : source.outcome === "penalties" ? " pens" : "";
        const xg = source.xg ? (home ? source.xg : source.xg.slice().reverse()) : null;
        if (c[2].text !== (score[0] > score[1] ? "W" : score[0] < score[1] ? "L" : "D") || c[3].text !== score.join("–") + ending
          || c[4].text !== (xg ? xg.map((v) => v.toFixed(1)).join("–") : "—")) recentOff.push(`${tag} ${team}: wrong recent score/xG orientation`);
      });
    }
    const hRows = [...html.matchAll(/<tr\b([^>]*data-match-h2h-row="[^"]*"[^>]*)>([\s\S]*?)<\/tr>/g)];
    if (Array.isArray(f.h2h)) {
      knownH2h++; h2hRows += hRows.length;
      if (hRows.length !== f.h2h.length || hRows.length > 6) h2hOff.push(`${tag}: wrong meeting count`);
      f.h2h.forEach(([date, comp, home, away, hg, ag, hx, ax], i) => {
        const row = hRows[i], a = row && attrs(row[1]), c = row ? cells(row[2]) : [];
        if (!row || a["data-match-h2h-row"] !== [home, away, date].join("|") || date > RESULT.as_of
          || ![home, away].every((t) => t === f.home || t === f.away) || i && date > f.h2h[i - 1][0]
          || c[0]?.text !== date || c[2]?.attr["data-team"] !== home || c[3]?.text !== `${hg}–${ag}` || c[4]?.attr["data-team"] !== away
          || c[5]?.text !== (hx == null || ax == null ? "—" : `${hx.toFixed(1)}–${ax.toFixed(1)}`)) h2hOff.push(`${tag}: meeting row ${i} not the source history`);
      });
    } else { missingH2h++; if (hRows.length || !html.includes('data-match-h2h="unavailable"')) h2hOff.push(`${tag}: invented missing history`); }
  }
  check(cards > 0 && forecasts > 0 && !valueOff.length, `match card: ${cards} cards (${forecasts} forecasts/${playedCards} played), H/D/A and ${xgValues} xG values equal Fixtures; ${ratingValues} rating values and ${tops} likeliest scores equal source`, valueOff.slice(0, 4).join("; "));
  if (stakeValues) check(awayValues > 0 && !stakeOff.length, `match card: all ${stakeValues} fate-by-result values equal fixture stakes, including ${awayValues} away values reversed`, stakeOff.slice(0, 4).join("; "));
  else console.log("  skip    match card stakes identity (no stakes in this snapshot)");
  if (recentRows) check(!recentOff.length, `match card: ${recentRows} last-five rows are real earlier matches in this competition, with side-oriented scores/xG`, recentOff.slice(0, 4).join("; "));
  else console.log("  skip    match card last-five identity (no played fixtures available)");
  if (knownH2h) check(!h2hOff.length, `match card: ${h2hRows} head-to-head rows on ${knownH2h} forecasts equal the payload, newest six, both sides and cutoff respected`, h2hOff.slice(0, 4).join("; "));
  else console.log(`  skip    match card head-to-head equality (${missingH2h} older fixtures without h2h)`);
  if (missingH2h && knownH2h) console.log(`  skip    match card head-to-head equality for ${missingH2h} played/older fixtures without h2h (unavailable state checked)`);
  const sample = selected.values().next().value;
  if (sample) {
    const absent = {...sample, f: {...sample.f}}; delete absent.f.h2h;
    check(X.matchH2hHtml(absent).includes('data-match-h2h="unavailable"') && X.matchH2hHtml({...sample, f: {...sample.f, h2h: []}}).includes('data-match-h2h="0"'),
      "match card: 2 history fallbacks distinguish an older missing field from zero recorded meetings");
  }
  const hookCounts = {fixtures: cards, gameweek: 0, big: 0, team: 0};
  if (GWD) {
    for (const g of Object.values({...GWD.leagues, ...GWD.phases})) {
      const round = X.defaultGw(g), html = X.gwTable(g, round, GWD.worlds), shown = new Set([...html.matchAll(/data-match="([^"]*)"/g)].map((m) => decode(m[1])));
      for (const f of g.fixtures.filter((f) => f.round === round)) { hookCounts.gameweek++; if (!shown.has(mkey(f))) hookOff.push(`${mkey(f)}: missing Gameweek match route`); }
    }
    if (Object.values(GWD.leagues).some((g) => g.fixtures.some((f) => f.stakes))) {
      delete els.view; X.BIGMODE = "week"; await X.drawBigMatches();
      const rows = [...mk("view").innerHTML.matchAll(/<tr\b([^>]*data-match="[^"]*"[^>]*)>/g)]; hookCounts.big = rows.length;
      if (!rows.length) hookOff.push("Big matches has no match hooks");
    }
  }
  for (const [team, fixtures] of Object.entries(TEAMD)) {
    const html = X.teamPageHtml(team, fixtures), rows = [...html.matchAll(/<tr\b([^>]*data-team-fixture="[^"]*"[^>]*)>/g)];
    hookCounts.team += rows.length;
    for (const row of rows) { const a = attrs(row[1]); if (!a["data-match"] || a["data-team-fixture"].split("|").slice(1).join("|") !== a["data-match"]) hookOff.push(`${team}: team fixture has no matching route`); }
  }
  check(!hookOff.length, `match routes: ${hookCounts.fixtures} Fixtures rows, ${hookCounts.gameweek} Gameweek matches, ${hookCounts.big} Big matches and ${hookCounts.team} team-page rows keep their match keys`, hookOff.slice(0, 4).join("; "));
  if ((RESULT.version || 1) >= 11) check(typeof RESULT.model === "string" && RESULT.model.length > 0, `model stamp: payload v${RESULT.version} names ${RESULT.model || "missing"}`);
  else console.log("  skip    explicit model stamp (snapshot before payload11)");
}

// ---------------------------------------------------------------- next-round what-if
// Payload filtering is proved from raw counts in smoke. Here every serialized fate is weighted
// back to the projection, then every visible conditional row is read from all three panels.
{
  X.RESULT = RESULT; X.MATCHES = MATCHES; X.GW = GWD;
  const decode = (s) => s.replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">").replace(/&amp;/g, "&");
  const plain = (s) => decode(s.replace(/<[^>]*>/g, "")).trim();
  const attrs = (s) => Object.fromEntries([...s.matchAll(/([\w-]+)="([^"]*)"/g)].map((m) => [m[1], decode(m[2])]));
  const key = (f) => [f.competition, f.home, f.away, f.kickoff.slice(0, 10)].join("|");
  const equal = (a, b, tol = 1e-10) => a == null || b == null ? a == null && b == null : Math.abs(a - b) <= tol;
  const base = (entry, team, fate) => {
    const block = (entry.kind === "league" ? RESULT.leagues : RESULT.uefa).find((b) => b.competition === entry.competition);
    const t = block?.teams.find((r) => r.team === team);
    if (!t) return null;
    const ucl = t.p_ucl ?? t.p_top4;
    return {title: t.p_win, ucl, euro: ucl == null ? null : ucl + (t.p_uel || 0) + (t.p_uecl || 0), down: t.p_releg,
      top8: t.p_top8, top24: t.p_out == null ? null : 1 - t.p_out, r16: t.p_r16, win: t.p_win}[fate] ?? null;
  };
  const all = X.matchFixtures(), eligible = all.filter((e) => Object.hasOwn(e.f, "whatif"));
  const payloadOff = [], renderOff = [], scopeOff = [];
  let fates = 0, stakeCells = 0, awayStakeCells = 0, rendered = 0, panels = 0, missingBase = 0, fixtureButtons = 0, collapsed = 0;
  X.WHATIF_FIXTURE = null; X.WHATIF_CARD_OPEN.clear();
  for (const entry of eligible) {
    const {f, keys} = entry, source = f.whatif, po = [f.ladder?.h1, f.ladder?.d, f.ladder?.a1], tag = key({...f, competition: entry.competition});
    if (!["league", "uefa"].includes(entry.kind) || f.result || !source || Array.isArray(source)) payloadOff.push(`${tag}: ineligible field`);
    for (const [team, values] of Object.entries(source || {})) {
      if (values.length !== 4 || values.some((v) => !Array.isArray(v) || v.length !== 3)) { payloadOff.push(`${tag} ${team}: not four fates by three results`); continue; }
      values.forEach((v, k) => {
        const now = base(entry, team, keys[k]);
        fates++;
        if (v.some((p, o) => p != null && (!Number.isFinite(p) || p < 0 || p > 1) || p == null && po[o] > 0)) payloadOff.push(`${tag} ${team} ${keys[k]}: invalid/unseen conditional`);
        if (now == null) { missingBase++; return; }
        const weighted = v.reduce((s, p, o) => s + po[o] * (p ?? 0), 0);
        // Four-place H/D/A + three-place conditionals + up to three four-place Europe terms.
        if (Math.abs(weighted - now) > .0008 + 1e-9) payloadOff.push(`${tag} ${team} ${keys[k]}: weighted ${weighted}, now ${now}`);
        const side = team === f.home ? 0 : team === f.away ? 1 : -1;
        if (side >= 0 && f.stakes) {
          const raw = f.stakes[side][k], wanted = Array.isArray(raw) ? raw : [raw, raw, raw];
          v.forEach((p, o) => { stakeCells++; if (side) awayStakeCells++; if (!equal(p, wanted[o])) payloadOff.push(`${tag} ${team} ${keys[k]}: conditional differs from playing-side stakes`); });
        }
      });
    }
    const card = X.whatifCardHtml(entry), opening = card.match(/<details\b([^>]*)>/);
    if (Object.keys(source || {}).length) {
      collapsed++;
      if (!opening || /\sopen(?:\s|$)/.test(opening[1]) || attrs(opening[1])["data-whatif-card"] !== tag) scopeOff.push(`${tag}: card not collapsed initially`);
      if (!X.matchCardHtml(entry).includes(`data-whatif-card="${tag.replace(/&/g, "&amp;").replace(/"/g, "&quot;")}"`)) scopeOff.push(`${tag}: match card has no explorer`);
    } else if (card) scopeOff.push(`${tag}: empty source creates card control`);
    for (let result = 0; result < 3; result++) {
      panels++;
      const expected = []; let omitted = 0, missing = 0, candidates = 0;
      for (const [team, values] of Object.entries(source || {})) keys.forEach((fate, k) => {
        candidates++;
        const now = base(entry, team, fate), conditional = values[k]?.[result];
        if (now == null || conditional == null || !Number.isFinite(conditional)) { missing++; return; }
        const delta = conditional - now;
        if (Math.abs(delta) + 1e-12 < .005) { omitted++; return; }
        expected.push({team, fate, now, conditional, delta});
      });
      expected.sort((a, b) => Math.abs(b.delta) - Math.abs(a.delta) || a.team.localeCompare(b.team) || keys.indexOf(a.fate) - keys.indexOf(b.fate));
      const html = X.whatifPanelHtml(entry, result), panel = attrs(html.match(/<div\b([^>]*)>/)?.[1] || "");
      const rows = [...html.matchAll(/<tr\b([^>]*data-whatif-row="[^"]*"[^>]*)>([\s\S]*?)<\/tr>/g)];
      const pills = [...html.matchAll(/<button\b([^>]*data-whatif-result="[012]"[^>]*)>/g)].map((m) => attrs(m[1]));
      if (+panel["data-whatif-result-table"] !== result || +panel["data-whatif-shown"] !== expected.length
        || +panel["data-whatif-omitted"] !== omitted || +panel["data-whatif-missing"] !== missing
        || +panel["data-whatif-candidates"] !== candidates || rows.length !== expected.length
        || pills.length !== 3 || pills.some((p, i) => +p["data-whatif-result"] !== i || p["aria-pressed"] !== String(i === result))) renderOff.push(`${tag} result${result}: rows/counts/selected pill`);
      if (!expected.length && !plain(html).includes("No fate has an available move")) renderOff.push(`${tag} result${result}: no empty state`);
      rows.forEach((row, i) => {
        rendered++;
        const a = attrs(row[1]), c = [...row[2].matchAll(/<td\b([^>]*)>([\s\S]*?)<\/td>/g)].map((m) => ({attr: attrs(m[1]), text: plain(m[2])})), want = expected[i];
        if (!want || a["data-whatif-row"] !== `${want.team}|${want.fate}` || c.length !== 5 || c[0].attr["data-team"] !== want.team) { renderOff.push(`${tag} result${result}: membership/order/header mismatch`); return; }
        for (const field of ["now", "conditional", "delta"]) if (!equal(+a[`data-whatif-${field}`], want[field])) renderOff.push(`${tag} ${want.team} ${want.fate}: wrong raw ${field}`);
        const numeric = (s) => parseFloat(s.replace(/[▲▼+%\s]/g, "").replace("−", "-"));
        if (!equal(numeric(c[2].text) / 100, want.now, .0005 + 1e-9) || !equal(numeric(c[3].text) / 100, want.conditional, .0005 + 1e-9)
          || !equal(numeric(c[4].text) / 100, Math.abs(want.delta), .0005 + 1e-9)) renderOff.push(`${tag} ${want.team} ${want.fate}: wrong visible Now/with-result/delta`);
        const helpful = want.fate === "down" ? want.delta < 0 : want.delta > 0;
        if (!(c[4].attr.class || "").split(/\s+/).includes(helpful ? "up" : "down")
          || !c[4].text.includes(want.delta > 0 ? "▲" : "▼")) renderOff.push(`${tag} ${want.team} ${want.fate}: delta sign or benefit colour`);
      });
    }
  }
  for (const entry of all) {
    const source = (MATCHES.fixtures || []).find((f) => key(f) === key({...entry.f, competition: entry.competition}));
    const available = !entry.f.result && ["league", "uefa"].includes(entry.kind) && Object.keys(source?.whatif || {}).length > 0;
    const button = X.whatifFixtureButton(entry.g, entry.f, entry.keys), a = attrs(button.match(/<button\b([^>]*)>/)?.[1] || "");
    if (button) fixtureButtons++;
    if (!!button !== available || button && (a["data-whatif-open"] !== key({...entry.f, competition: entry.competition}) || a["aria-expanded"] !== "false")) scopeOff.push(`${key(entry.f)}: wrong Fixtures eligibility/control`);
  }
  if (eligible.length) {
    check(fates > 0 && !payloadOff.length, `what-if payload: ${fates} serialized side-fates weight back to Now within 0.08pp; ${stakeCells} playing values (${awayStakeCells} away) equal stakes`, payloadOff.slice(0, 4).join("; "));
    check(panels > 0 && rendered > 0 && !renderOff.length, `what-if panels: ${rendered} visible fate rows across ${panels} H/D/A panels equal payload/Now/delta, with exact omission counts and survival colours`, renderOff.slice(0, 4).join("; "));
    check(collapsed > 0 && fixtureButtons > 0 && !scopeOff.length, `what-if controls: ${collapsed} Match cards start collapsed; ${fixtureButtons} Fixtures buttons only for eligible next matches`, scopeOff.slice(0, 4).join("; "));
    if (missingBase) console.log(`  skip    what-if weighted equality for ${missingBase} fates missing an unconditional field`);
    const sample = eligible.find((e) => Object.keys(e.f.whatif).length), tag = key({...sample.f, competition: sample.competition});
    const hosts = [0, 1].map(() => ({dataset: {whatifHost: tag}, innerHTML: "", querySelectorAll: () => []}));
    const details = {dataset: {whatifCard: tag}, open: false};
    const buttons = [0, 1, 2].map((i) => ({dataset: {whatifResult: String(i)}, closest: () => hosts[0]}));
    const target = {querySelectorAll: (selector) => selector === "[data-whatif-result]" ? buttons : selector === "[data-whatif-card]" ? [details] : []};
    const oldQuery = document.querySelectorAll;
    document.querySelectorAll = (selector) => selector === "[data-whatif-host]" ? hosts : [];
    X.wireWhatif(target);
    let stopped = 0, stateOK = true;
    for (let result = 0; result < 3; result++) {
      buttons[result].onclick({stopPropagation() { stopped++; }});
      X.WHATIF_FIXTURE = tag;
      stateOK &&= X.WHATIF_RESULT[tag] === result && hosts.every((h) => h.innerHTML === X.whatifPanelHtml(sample, result))
        && X.whatifFixturesHtml(sample.competition).includes(`data-whatif-result-table="${result}"`);
    }
    details.open = true; details.ontoggle();
    stateOK &&= /<details\b[^>]*\sopen>/.test(X.whatifCardHtml(sample));
    details.open = false; details.ontoggle();
    stateOK &&= !/<details\b[^>]*\sopen>/.test(X.whatifCardHtml(sample));
    document.querySelectorAll = oldQuery; X.WHATIF_FIXTURE = null; delete X.WHATIF_RESULT[tag];
    check(stateOK && stopped === 3, "what-if interactions: 3 H/D/A clicks stop the match route, update both hosts and Fixtures selection; details expand/collapse");
  } else console.log("  skip    what-if payload/panels/controls (older snapshot without next-round conditional rows)");
  // Missing-field fallback must stay real even when the current snapshot carries the feature.
  const sample = all.find((e) => !e.f.result && e.kind === "league");
  if (sample) {
    const stripped = {fixtures: (MATCHES.fixtures || []).map((f) => { const c = {...f}; delete c.whatif; return c; })};
    const f = {...sample.f}; delete f.whatif;
    const old = {...sample, f}; X.MATCHES = stripped;
    const missingOK = X.whatifSource(f, old.competition) === null && X.whatifCardHtml(old) === "" && X.whatifFixtureButton(old.g, f, old.keys) === "";
    const unchanged = {...old, f: {...f, whatif: {[f.home]: old.keys.map((fate) => [base(old, f.home, fate), null, base(old, f.home, fate)])}}};
    const small = X.whatifPanelHtml(unchanged, 0), absent = X.whatifPanelHtml(unchanged, 1);
    const sa = attrs(small.match(/<div\b([^>]*)>/)?.[1] || ""), aa = attrs(absent.match(/<div\b([^>]*)>/)?.[1] || "");
    check(missingOK && +sa["data-whatif-shown"] === 0 && +sa["data-whatif-candidates"] === 4
      && +sa["data-whatif-omitted"] > 0 && +aa["data-whatif-missing"] === 4
      && plain(small).includes("No fate has an available move") && plain(absent).includes("No fate has an available move"),
      "what-if fallbacks: older missing field offers no control; four unchanged/unseen fates show explicit empty and unavailable counts");
    X.MATCHES = MATCHES;
  } else console.log("  skip    what-if legacy/empty-state probes (no projected league fixture)");
}

// The retired sampled-season screen is absent even while retained samples support accounting.
{
 X.RESULT=RESULT;const blocks=[...RESULT.leagues,...RESULT.uefa],old={...X.VIEWSEL};
 check(blocks.length>0&&blocks.every(b=>!X.viewsFor(b.competition).some(([k,t])=>k==='sample'||t==='A season')),
  'Retired A season:league/UEFA view pickers exclude the sampled-season screen regardless of retained samples');
 X.VIEWSEL.league='sample';X.VIEWSEL.uefa='sample';
 check(blocks.every(b=>X.viewOf(b.competition)==='overview'),'Retired A season:old view=sample links resolve to Overview');
 for(const key of Object.keys(X.VIEWSEL))delete X.VIEWSEL[key];Object.assign(X.VIEWSEL,old);
}

// ---------------------------------------------------------------- players in the Stats hub
{
  X.RESULT = RESULT; X.PLAYERS = PLAYERS; X.PLAYERS_FOR = RESULT; X.PLAYERS_STATUS = PLAYERS ? "ready" : "missing";
  const decode = (s) => s.replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&amp;/g, "&");
  const plain = (s) => decode(s.replace(/<[^>]*>/g, "")).trim();
  const attrs = (s) => Object.fromEntries([...s.matchAll(/([\w-]+)="([^"]*)"/g)].map((m) => [m[1], decode(m[2])]));
  const metrics = ["goals", "xg", "finishing", "xg90", "assists", "shots"], fields = ["matches", "minutes", "goals", "pen_goals", "assists", "shots", "xg", "xgot"];
  const value = (r, metric) => metric === "finishing" ? r.goals != null && r.xg != null ? r.goals - r.xg : null
    : metric === "xg90" ? r.xg != null && r.minutes > 0 ? 90 * r.xg / r.minutes : null : r[metric];
  const sourceRows = (block, team) => block.players.flatMap((p) => {
    const s = team === "all" ? p : p.by_team?.[team];
    return s ? [{id: p.id, name: p.name, teams: team === "all" ? p.teams : [team],
      ...Object.fromEntries(fields.map((k) => [k, Number.isFinite(s[k]) ? s[k] : null]))}] : [];
  });
  const expectedLeaders = (block, metric, team, floor) => {
    const source = sourceRows(block, team), known = source.filter((r) => value(r, metric) != null);
    const eligible = known.filter((r) => metric !== "xg90" || r.minutes >= floor).sort((a, b) => value(b, metric) - value(a, metric)
      || (b.goals ?? -1) - (a.goals ?? -1) || (b.minutes ?? -1) - (a.minutes ?? -1)
      || a.name.localeCompare(b.name) || String(a.id).localeCompare(String(b.id)));
    return {rows: eligible.slice(0, 50), total: source.length, eligible: eligible.length,
      unknown: source.length - known.length, belowFloor: known.length - eligible.length, omitted: Math.max(0, eligible.length - 50)};
  };
  const good = X.playersPayload(), off = [], scorerOff = [], hubOff = [];
  let tables = 0, rows = 0, filters = 0, empty = 0, badgeMarks = 0, scorers = 0, scorerSides = 0;
  let badgeIndex = {};
  try { badgeIndex = JSON.parse(readFileSync(new URL("../../data/badges/index.json", ROOT), "utf8")); } catch {}
  X.BADGES = badgeIndex;
  if (good) {
    for (const [comp, block] of Object.entries(good.competitions)) {
      if (!(block.coverage.covered > 0 && block.players.length)) continue;
      const projected = [...RESULT.leagues, ...RESULT.uefa, ...(RESULT.cups || [])].find((b) => b.competition === comp) || {competition: comp, teams: []};
      const teams = ["all", ...new Set(block.players.flatMap((p) => Object.keys(p.by_team || {})))].sort((a, b) => a === "all" ? -1 : b === "all" ? 1 : a.localeCompare(b));
      for (const metric of metrics) for (const team of teams) for (const floor of metric === "xg90" && team === "all" ? [90, 180, 270, 450, 900] : [180]) {
        tables++; if (team !== "all") filters++;
        const want = expectedLeaders(block, metric, team, floor), data = X.playerLeadersData(comp, metric, team, floor);
        if (["total", "eligible", "unknown", "belowFloor", "omitted"].some((k) => data[k] !== want[k]) || JSON.stringify(data.rows.map((r) => r.id)) !== JSON.stringify(want.rows.map((r) => r.id))) off.push(`${comp} ${metric} ${team}/${floor}: ranking/coverage/floor`);
        const html = X.playerLeadersHtml(projected, metric, team, floor), root = attrs(html.match(/<div\b([^>]*)>/)?.[1] || "");
        const shown = [...html.matchAll(/<tr\b([^>]*data-player-row="[^"]*"[^>]*)>([\s\S]*?)<\/tr>/g)];
        if (root["data-player-leaders"] !== comp || root["data-player-selected-metric"] !== metric || root["data-player-selected-team"] !== team
          || +root["data-player-selected-floor"] !== floor || shown.length !== want.rows.length || (html.match(/<table\b/g) || []).length !== (want.rows.length ? 1 : 0)
          || html.includes("data-player-floor") !== (metric === "xg90")) off.push(`${comp} ${metric} ${team}/${floor}: wrong controls/table/selection`);
        const controls = [...html.matchAll(/<select\b([^>]*)>([\s\S]*?)<\/select>/g)];
        for (const [attribute, selected] of [["data-player-metric", metric], ["data-player-team", team], ...(metric === "xg90" ? [["data-player-floor", String(floor)]] : [])]) {
          const select = controls.find((m) => Object.hasOwn(attrs(m[1]), attribute));
          const options = [...(select?.[2] || "").matchAll(/<option\b([^>]*)>/g)];
          // HTML's first option is selected implicitly when Every club is active.
          const chosen = options.find((o) => /\bselected\b/.test(o[1])) || options[0];
          if (!chosen || attrs(chosen[1]).value !== selected) off.push(`${comp} ${metric} ${team}: wrong selected control`);
        }
        if (!want.rows.length) { empty++; if (!html.includes('data-player-empty="1"')) off.push(`${comp} ${metric} ${team}: empty selection unexplained`); }
        for (const [count, phrase] of [[want.unknown, "players without complete"], [want.belowFloor, "below the minutes floor"], [want.omitted, "beyond the first 50"]]) if (count && !plain(html).includes(`${count} ${phrase}`)) off.push(`${comp} ${metric} ${team}: missing exclusion count`);
        shown.forEach((row, i) => {
          rows++;
          const a = attrs(row[1]), expected = want.rows[i], cells = [...row[2].matchAll(/<td\b([^>]*)>([\s\S]*?)<\/td>/g)].map((m) => ({a: attrs(m[1]), html: m[2], text: plain(m[2])}));
          const numeric = parseFloat(cells[3]?.text.replace("−", "-")), raw = value(expected, metric), precision = ["xg", "xg90", "finishing"].includes(metric) ? .005 + 1e-9 : 0;
          if (a["data-player-row"] !== String(expected.id) || +a["data-player-value"] !== raw || a["data-player-minutes"] !== String(expected.minutes ?? "")
            || a["data-player-team"] !== team || cells.length !== 4 || cells[2].text !== String(expected.minutes ?? "—") || Math.abs(numeric - raw) > precision) off.push(`${comp} ${metric} ${expected.id}: wrong metric/minutes cells`);
          const linked = [...(cells[1]?.html || "").matchAll(/data-team="([^"]*)"/g)].map((m) => decode(m[1]));
          if (JSON.stringify(linked) !== JSON.stringify(expected.teams)) off.push(`${comp} ${metric} ${expected.id}: wrong club contributions/routes`);
          const badges = [...(cells[0]?.html || "").matchAll(/<img\b([^>]*)\/?\s*>/g)].map((m) => attrs(m[1]));
          const knownBadges = expected.teams.filter((t) => badgeIndex[t]); badgeMarks += badges.length;
          if (badges.length !== knownBadges.length || badges.some((b, k) => b["data-team"] !== knownBadges[k] || b.src !== "/badges/" + encodeURIComponent(badgeIndex[knownBadges[k]]))) off.push(`${comp} ${metric} ${expected.id}: wrong side badge`);
        });
      }
      if ([...RESULT.leagues, ...RESULT.uefa].includes(projected)) {
        X.HUBSEL = "players"; X.PLAYER_METRIC = "goals"; X.PLAYER_TEAM = "all"; X.PLAYER_MINUTES = 180;
        X.drawStatsHub(projected);
        const html = mk("cview").innerHTML;
        if ((html.match(/data-hub="players"/g) || []).length !== 1 || !html.includes('data-hub="players" aria-pressed="true"') || (html.match(/<table\b/g) || []).length !== 1) hubOff.push(`${comp}: Players is not one compact Stats hub mode/table`);
      }
    }
    const teams = [...new Set(Object.values(good.competitions).flatMap((b) => Object.keys(b.teams)))];
    for (const team of teams) {
      const pooled = new Map(); let covered = 0, played = 0;
      for (const block of Object.values(good.competitions)) {
        covered += block.teams[team]?.covered || 0; played += block.teams[team]?.played || 0;
        for (const p of block.players) {
          const part = p.by_team?.[team]; if (!part) continue;
          const id = String(p.id), r = pooled.get(id) || {id: p.id, name: p.name, goals: 0, unknown: false};
          if (Number.isFinite(part.goals)) r.goals += part.goals; else r.unknown = true;
          pooled.set(id, r);
        }
      }
      const all = [...pooled.values()], expected = all.filter((r) => !r.unknown && r.goals > 0).sort((a, b) => b.goals - a.goals || a.name.localeCompare(b.name) || String(a.id).localeCompare(String(b.id))).slice(0, 3);
      const data = X.teamScorerRows(team), html = X.teamScorersHtml(team), shown = [...html.matchAll(/<div\b([^>]*data-scorer-row="[^"]*"[^>]*)>([\s\S]*?)<\/div>/g)];
      scorerSides++; scorers += shown.length;
      if (data.covered !== covered || data.played !== played || data.unknown !== all.filter((r) => r.unknown).length || shown.length !== expected.length
        || JSON.stringify(data.rows.map((r) => [r.id, r.goals])) !== JSON.stringify(expected.map((r) => [r.id, r.goals]))) scorerOff.push(`${team}: incomplete/other-club scorer totals or coverage`);
      if (!covered && !html.includes("No covered player stats for this side")) scorerOff.push(`${team}: uncovered side lacks an explicit unavailable state`);
      shown.forEach((row, i) => { const a = attrs(row[1]); if (a["data-scorer-row"] !== String(expected[i].id) || +a["data-scorer-goals"] !== expected[i].goals || !plain(row[2]).endsWith(String(expected[i].goals))) scorerOff.push(`${team}: displayed scorer differs`); });
    }
    check(rows > 0 && tables > 0 && !off.length, `players: ${rows} rendered leaders across ${tables} metric/floor tables (${filters} club selections), exact source values/order/unknowns; ${badgeMarks} side badges and ${empty} explicit empty selections`, off.slice(0, 4).join("; "));
    check(scorerSides > 0 && scorers > 0 && !scorerOff.length, `top scorers: ${scorers} rows across ${scorerSides} sides equal strict all-competition club contributions, top3 with exact coverage`, scorerOff.slice(0, 4).join("; "));
    check(!hubOff.length, "Players is offered inside every covered league/UEFA Stats hub with one selected table", hubOff.slice(0, 4).join("; "));
    const block = [...RESULT.leagues, ...RESULT.uefa].find((b) => X.hasPlayerData(b.competition));
    if (block) {
      const container = mk("cview"), originalQuery = container.querySelectorAll;
      const metric = {value: "xg90"}, club = {value: Object.keys(good.competitions[block.competition].teams)[0]}, floor = {value: "900"};
      container.querySelectorAll = (s) => s === "select[data-player-metric]" ? [metric] : s === "select[data-player-team]" ? [club] : s === "select[data-player-floor]" ? [floor] : [];
      X.HUBSEL = "players"; X.PLAYER_TEAM = "all"; X.drawStatsHub(block); metric.onchange(); floor.onchange(); club.onchange();
      const controlsOK = X.PLAYER_METRIC === "xg90" && X.PLAYER_MINUTES === 900 && X.PLAYER_TEAM === club.value
        && container.innerHTML.includes('data-player-selected-metric="xg90"') && container.innerHTML.includes('data-player-selected-floor="900"');
      container.querySelectorAll = originalQuery;
      X.FOCUS = block.teams[0].team; X.TEAM_PAGE = false; X.renderTeamCard();
      const cardOK = mk("teamcard").innerHTML.includes(X.teamScorersHtml(X.FOCUS));
      const pageOK = X.teamPageHtml(X.FOCUS, TEAMD[X.FOCUS] || []).includes(X.teamScorersHtml(X.FOCUS));
      X.FOCUS = null; X.TEAM_PAGE = false;
      check(controlsOK && cardOK && pageOK, "players: metric/club/minutes controls update the single table; team card and full page reuse their exact top scorers");
    }
  } else console.log(`  skip    player leaders/scorers identities (${PLAYERS ? "players.json season/cutoff does not match this snapshot" : "older snapshot without players.json"})`);
  // Unknown/zero/minutes-floor and transferred-player rules need deliberate edge cases too.
  const part = (goals, minutes, xg) => ({matches: 1, goals, minutes, xg, assists: 0, shots: 1, pen_goals: 0, xgot: 0, known: {}});
  const synthetic = {season: RESULT.params.season, as_of: RESULT.as_of, competitions: {
    "Test Players": {coverage: {played: 2, covered: 2}, teams: {Alpha: {played: 1, covered: 1}, Beta: {played: 1, covered: 1}}, players: [
      {id: "1", name: "Transfer", teams: ["Alpha", "Beta"], ...part(3, 180, 1.2), matches: 2, by_team: {Alpha: part(1, 90, .5), Beta: part(2, 90, .7)}},
      {id: "2", name: "Below", teams: ["Beta"], ...part(4, 179, 1.5), by_team: {Beta: part(4, 179, 1.5)}},
      {id: "3", name: "Unknown", teams: ["Beta"], ...part(null, null, null), by_team: {Beta: part(null, null, null)}},
      {id: "4", name: "Zero minutes", teams: ["Beta"], ...part(0, 0, 0), by_team: {Beta: part(0, 0, 0)}}]},
    "Other competition": {coverage: {played: 1, covered: 1}, teams: {Alpha: {played: 1, covered: 1}}, players: [{id: "1", name: "Transfer", teams: ["Alpha"], ...part(null, 90, 0), by_team: {Alpha: part(null, 90, 0)}}]}}};
  X.PLAYERS = synthetic; X.PLAYERS_FOR = RESULT; X.PLAYERS_STATUS = "ready";
  const edge = X.playerLeadersData("Test Players", "xg90", "all", 180), transferred = X.playerRows("Test Players", "Alpha"), unknown = X.teamScorerRows("Alpha");
  check(edge.rows.length === 1 && edge.rows[0].id === "1" && edge.unknown === 2 && edge.belowFloor === 1
    && transferred.length === 1 && transferred[0].goals === 1 && transferred[0].minutes === 90
    && unknown.rows.length === 0 && unknown.unknown === 1 && X.teamScorersHtml("Alpha").includes("No scorers with complete goal totals"),
    "players: 4 edge cases keep a180-minute boundary, exclude179/zero/unknown minutes, isolate a transferred club and reject partially unknown scorer totals");
  const sampleBlock = RESULT.leagues[0], guards = [null, {...synthetic, as_of: "1900-01-01"}, {...synthetic, season: RESULT.params.season - 1}];
  let guardOK = true;
  for (const payload of guards) {
    X.PLAYERS = payload; X.PLAYERS_FOR = RESULT; X.PLAYERS_STATUS = "missing"; X.HUBSEL = "players";
    X.drawStatsHub(sampleBlock);
    guardOK &&= X.playersPayload() === null && !X.hasPlayerData(sampleBlock.competition) && !mk("cview").innerHTML.includes('data-hub="players"')
      && X.playerLeadersHtml(sampleBlock).includes('data-player-unavailable="1"');
  }
  X.PLAYERS = synthetic; X.PLAYERS_FOR = {...RESULT};
  guardOK &&= X.playersPayload() === null;
  check(guardOK, "players: 4 missing/cutoff/season/snapshot-identity guards hide the mode, preserve team statistics and explain unavailable player data in v11 too");
  // Mock fetch only: repeated visits share one request, and late old-snapshot responses cannot
  // attach to a new RESULT. This exercises the loader without any external or localhost I/O.
  const originalFetch = globalThis.fetch; let requests = 0, resolve;
  const reset = (result) => { X.RESULT = result; X.PLAYERS_FOR = null; X.PLAYERS = null; X.PLAYERS_STATUS = "unrequested"; X.PLAYERS_PROMISE = null; };
  const response = (payload, ok = true) => ({ok, status: ok ? 200 : 404, json: async () => payload});
  const resultA = {...RESULT}; reset(resultA);
  let scorerStatesOK = X.teamScorersHtml("Alpha").includes("Loading player stats");
  globalThis.fetch = () => { requests++; return new Promise((r) => { resolve = r; }); };
  const a = X.ensurePlayers(), b = X.ensurePlayers();
  scorerStatesOK &&= X.teamScorersHtml("Alpha").includes("Loading player stats");
  const shared = a === b && requests === 1;
  resolve(response(synthetic)); await a; await X.ensurePlayers();
  let loadOK = shared && requests === 1 && X.playersPayload() === synthetic;
  scorerStatesOK &&= !X.teamScorersHtml("Alpha").includes("Loading player stats");
  reset({...RESULT}); const old = X.ensurePlayers(), resultB = {...RESULT}; X.RESULT = resultB;
  scorerStatesOK &&= X.teamScorersHtml("Alpha").includes("Loading player stats");
  resolve(response(synthetic)); await old; loadOK &&= X.playersPayload() === null;
  reset(resultB); globalThis.fetch = async () => { requests++; return response({...synthetic, as_of: "1900-01-01"}); };
  await X.ensurePlayers(); loadOK &&= X.playersPayload() === null && X.PLAYERS_STATUS === "mismatch";
  scorerStatesOK &&= X.teamScorersHtml("Alpha").includes("Player stats unavailable") && !X.teamScorersHtml("Alpha").includes("Loading player stats");
  reset({...RESULT}); globalThis.fetch = async () => { requests++; return response({error: "missing"}, false); };
  await X.ensurePlayers(); const settledRequests = requests; await X.ensurePlayers();
  loadOK &&= X.playersPayload() === null && X.PLAYERS_STATUS === "missing" && requests === settledRequests;
  scorerStatesOK &&= X.teamScorersHtml("Alpha").includes("Player stats unavailable") && !X.teamScorersHtml("Alpha").includes("Loading player stats");
  globalThis.fetch = originalFetch; X.RESULT = RESULT; X.PLAYERS = PLAYERS; X.PLAYERS_FOR = RESULT; X.PLAYERS_STATUS = PLAYERS ? "ready" : "missing"; X.PLAYERS_PROMISE = null;
  X.HUBSEL = "team"; X.PLAYER_METRIC = "goals"; X.PLAYER_TEAM = "all"; X.PLAYER_MINUTES = 180;
  check(loadOK, "players loader: pending requests are shared; settled visits do not refetch; late old-snapshot, wrong-cutoff and404 responses never attach");
  check(scorerStatesOK, "players scorers: 6 unrequested/loading/ready/changed-snapshot/mismatch/missing states distinguish Loading from settled unavailable");
}

// ---------------------------------------------------------------- cup conditional stakes
{
  X.RESULT = RESULT; X.MATCHES = MATCHES; X.NEXT = NEXT; X.GW = GWD;
  const decode = (s) => s.replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&amp;/g, "&");
  const plain = (s) => decode(s.replace(/<[^>]*>/g, "")).trim();
  const attrs = (s) => Object.fromEntries([...s.matchAll(/([\w-]+)="([^"]*)"/g)].map((m) => [m[1], decode(m[2])]));
  const key = (f) => [f.competition, f.home, f.away, f.kickoff.slice(0, 10)].join("|");
  const cups = (MATCHES.fixtures || []).filter((f) => f.kind === "cup");
  const current = cups.filter((f) => f.stakes && Array.isArray(f.stakes_of) && f.stakes_of.length);
  const expand = (v) => Array.isArray(v) ? v.slice() : [v, v, v];
  const swing = (f, selected = null) => Math.max(0, ...f.stakes.flatMap((s) => s.flatMap((v, i) => {
    if (selected && !selected.includes(f.stakes_of[i])) return [];
    const finite = expand(v).filter((p) => p != null); return finite.length ? [Math.max(...finite) - Math.min(...finite)] : [0];
  })));
  const label = (fate) => fate === "win" ? "Win" : X.roundName(fate.toUpperCase());
  const off = [], hoverOff = [], bigOff = [];
  let fates = 0, values = 0, away = 0, hoverValues = 0, nextSides = 0, bigRows = 0;
  for (const f of current) {
    const block = CUPS.find((b) => b.competition === f.competition), keys = f.stakes_of;
    const allowed = [...(block?.rounds || []).map((r) => r.toLowerCase()), "win"];
    const start = allowed.indexOf(keys[0]);
    if (!block || start < 0 || JSON.stringify(keys) !== JSON.stringify(allowed.slice(start)) || f.stakes.length !== 2
      || f.stakes.some((r) => r.length !== keys.length) || f.score_basis !== "90min" || f.p_occurs !== 1) off.push(`${key(f)}: bad later-round suffix/shape/basis/occurrence`);
    const entry = X.findMatch([f.home, f.away, f.kickoff.slice(0, 10)].join("|"));
    if (!entry || JSON.stringify(entry.keys) !== JSON.stringify(keys)) { off.push(`${key(f)}: Matchcard lost per-fixture fate keys`); continue; }
    const html = X.matchCardHtml(entry), shown = [...html.matchAll(/<tr\b([^>]*data-match-stake="[^"]*"[^>]*)>([\s\S]*?)<\/tr>/g)];
    if (shown.length !== 2 * keys.length || !html.includes('data-match-score-basis="90min"') || X.whatifCardHtml(entry)) off.push(`${key(f)}: missing cup fates/90minute legend or invented What-if`);
    f.stakes.forEach((side, sideIndex) => side.forEach((raw, k) => {
      const row = expand(raw), team = sideIndex ? f.away : f.home, t = block.teams.find((r) => r.team === team);
      const now = t?.["p_" + keys[k]], po = [f.ladder.h1, f.ladder.d, f.ladder.a1]; fates++;
      if (now == null || row.some((p, o) => p == null && po[o] > 0 || p != null && (!Number.isFinite(p) || p < 0 || p > 1))
        || Math.abs(row.reduce((s, p, o) => s + po[o] * (p ?? 0), 0) - now) > .0007 + 1e-9) off.push(`${key(f)} ${team}/${keys[k]}: weighted conditional differs from unconditional`);
      const r = shown.find((r) => attrs(r[1])["data-match-stake"] === `${sideIndex ? "away" : "home"}|${keys[k]}`);
      const a = r && attrs(r[1]), cells = r ? [...r[2].matchAll(/<td\b[^>]*>([\s\S]*?)<\/td>/g)].map((m) => plain(m[1])) : [];
      const wanted = sideIndex ? row.slice().reverse() : row;
      if (!r || cells[0] !== label(keys[k])) off.push(`${key(f)}: missing generic fate label ${keys[k]}`);
      const stored = a?.["data-match-wdl"]?.split("|").map((v) => v === "" ? null : +v);
      wanted.forEach((p, o) => {
        values++; if (sideIndex) away++;
        const display = cells[o + 1] === "—" ? null : parseFloat(cells[o + 1]) / 100;
        if (!stored || stored[o] !== p || (p == null) !== (display == null) || p != null && Math.abs(display - p) > .0005 + 1e-9) off.push(`${key(f)} ${team}/${keys[k]}: rendered W/D/L differs`);
      });
    }));
  }
  for (const block of CUPS) {
    const overview = X.cup(block), rows = [...overview.matchAll(/<tr\b[^>]*>([\s\S]*?)<\/tr>/g)];
    for (const [team, n] of Object.entries(NEXT[block.competition] || {})) {
      const f = current.find((f) => f.competition === block.competition && f.kickoff === n.kickoff
        && (n.isHome ? f.home === team && f.away === n.opponent : f.away === team && f.home === n.opponent));
      if (!f) continue;
      nextSides++;
      const side = n.isHome ? 0 : 1, oriented = f.stakes[side].map((v) => n.isHome ? expand(v) : expand(v).reverse());
      if (JSON.stringify(n.keys) !== JSON.stringify(f.stakes_of) || JSON.stringify(n.stakes) !== JSON.stringify(oriented)) hoverOff.push(`${team}: Next keys/away direction differs`);
      const r = rows.find((r) => attrs(r[1].match(/<td\b([^>]*)>/)?.[1] || "")["data-team"] === team);
      const titles = [...(r?.[1] || "").matchAll(/title="([^"]*)"/g)].map((m) => decode(m[1])).join("\n");
      f.stakes_of.forEach((fate, i) => {
        const v = oriented[i], finite = v.filter((x) => x != null), range = finite.length ? Math.max(...finite) - Math.min(...finite) : 0;
        if (range < .005) return;
        hoverValues += 3;
        const wanted = `${label(fate)} ${v.map((p) => p == null ? "—" : (100 * p).toFixed(0)).join(" · ")}%`;
        if (!r || !titles.includes(wanted)) hoverOff.push(`${team}/${fate}: Overview hover omits/wrong conditional values`);
      });
    }
  }
  for (const [week, per] of [[true, 3], [false, 5]]) {
    const stop = new Date(RESULT.as_of + "T00:00:00"); stop.setDate(stop.getDate() + 8);
    const end = stop.toISOString().slice(0, 10), all = current.filter((f) => !f.result && f.kickoff.slice(0, 10) > RESULT.as_of && (!week || f.kickoff.slice(0, 10) < end));
    const wanted = X.COMP_ORDER.flatMap((comp) => all.filter((f) => f.competition === comp).sort((a, b) => swing(b, ["win"]) - swing(a, ["win"])
      || a.kickoff.localeCompare(b.kickoff) || a.home.localeCompare(b.home) || a.away.localeCompare(b.away)).slice(0, per));
    const data = X.bigMatchRows("cup", week), html = X.cupBigMatchesHtml(data), root = attrs(html.match(/<div\b([^>]*)>/)?.[1] || "");
    const rows = [...html.matchAll(/<tr\b([^>]*data-big-cup="[^"]*"[^>]*)>([\s\S]*?)<\/tr>/g)]; bigRows += rows.length;
    if (data.per !== per || data.stop !== end || data.all.length !== all.length || root["data-big-cup-fate"] !== "win" || +root["data-big-candidates"] !== all.length || +root["data-big-cups"] !== wanted.length
      || JSON.stringify(data.top.map((r) => key(r.f))) !== JSON.stringify(wanted.map(key)) || rows.length !== wanted.length) bigOff.push(`${week ? "week" : "season"}: wrong window/count/cap/order`);
    rows.forEach((row, i) => {
      const a = attrs(row[1]), f = wanted[i], c = [...row[2].matchAll(/<td\b[^>]*>([\s\S]*?)<\/td>/g)].map((m) => plain(m[1]));
      const trophySwing = swing(f, ["win"]), shownSwing = parseFloat(c[9]) / 100;
      if (a["data-big-cup"] !== key(f) || c.length !== 10 || c[7] !== "—"
        || (trophySwing >= .0005 ? !Number.isFinite(shownSwing) || Math.abs(shownSwing - trophySwing) > .0005 + 1e-9 : c[9] !== "—")
        || [f.ladder.h1, f.ladder.d, f.ladder.a1].some((p, o) => Math.abs(parseFloat(c[4 + o]) / 100 - p) > .0005 + 1e-9)) bigOff.push(`${key(f)}: wrong Bigcup probability/xG/swing cells`);
    });
  }
  if (current.length) {
    check(fates > 0 && values > 0 && away > 0 && !off.length, `cup stakes: ${fates} serialized fates recover unconditional chances; ${values} Matchcard values (${away} away reversed) preserve per-tie keys and90-minute basis`, off.slice(0, 4).join("; "));
    check(nextSides > 0 && hoverValues > 0 && !hoverOff.length, `cup next ties: ${nextSides} side-oriented Next records and ${hoverValues} fate values in Overview hovers equal their own fixture`, hoverOff.slice(0, 4).join("; "));
    check(bigRows > 0 && !bigOff.length, `Bigcup matches: ${bigRows} rows across week/season, exact3/5percup caps, window/order/HDA and trophy-only swing; unavailable projectedxG stays blank`, bigOff.slice(0, 4).join("; "));
  } else console.log(`  skip    cup conditional stakes/Overview/Bigcup identities (${cups.length} older cup forecasts without per-fixture later-round fates)`);
  if (CUPS.length) {
    const date = (offset) => { const day = new Date(RESULT.as_of + "T00:00:00Z"); day.setUTCDate(day.getUTCDate() + offset); return day.toISOString().slice(0, 10) + " 15:00:00"; };
    const base = {kind: "cup", competition: CUPS[0].competition, stakes_of: ["qf", "win"], ladder: {h1: .4, d: .2, a1: .4}, score_basis: "90min", p_occurs: 1};
    const small = {...base, home: "Earlier Alpha", away: "Earlier Beta", kickoff: date(1), stakes: [[[1, .5, 0], [.12, .1, .08]], [[0, .5, 1], [.08, .1, .12]]]};
    const large = {...base, home: "Later Gamma", away: "Later Delta", kickoff: date(2), stakes: [[[1, .5, 0], [.7, .4, .2]], [[0, .5, 1], [.2, .4, .7]]]};
    X.MATCHES = {...MATCHES, fixtures: [small, large]};
    const ranked = X.bigMatchRows("cup", true), html = X.cupBigMatchesHtml(ranked);
    const shown = [...html.matchAll(/<tr\b([^>]*data-big-cup="[^"]*"[^>]*)>([\s\S]*?)<\/tr>/g)];
    const swings = shown.map((r) => parseFloat([...r[2].matchAll(/<td\b[^>]*>([\s\S]*?)<\/td>/g)].at(-1)[1].replace(/<[^>]*>/g, "")));
    check(ranked.top.length === 2 && ranked.top[0].f.home === large.home && JSON.stringify(swings) === JSON.stringify([50, 4]),
      "Bigcup ranking: 2 equal100pp next-round swings rank by50pp/4pp trophy swings and display those values",
      JSON.stringify({competition: CUPS[0].competition, order: ranked.top.map((r) => r.f.home), swings}));
    X.MATCHES = MATCHES;
  }
  const legacy = {...MATCHES, fixtures: (MATCHES.fixtures || []).map((f) => {
    if (f.kind !== "cup") return f;
    const old = {...f}; delete old.stakes; delete old.stakes_of; delete old.score_basis; return old;
  })};
  X.MATCHES = legacy; X.NEXT = X.indexNextFixtures(legacy);
  const legacyBig = X.cupBigMatchesHtml(X.bigMatchRows("cup", true));
  let oldOK = !X.cupStakesAvailable() && legacyBig.includes("unavailable in this snapshot") && legacyBig.includes('data-big-cups="0"');
  const old = legacy.fixtures.find((f) => f.kind === "cup");
  if (old) {
    const entry = X.findMatch([old.home, old.away, old.kickoff.slice(0, 10)].join("|")), html = X.matchCardHtml(entry);
    oldOK &&= html.includes('data-match-score-basis="stored"') && !html.includes("data-match-stake=");
    const partial = {...entry, f: {...entry.f, score_basis: "90min", p_occurs: .25, stakes_unavailable: "conditional_fixture"}};
    const partialHtml = X.matchCardHtml(partial);
    oldOK &&= partialHtml.includes('data-match-occurs="0.25"') && partialHtml.includes("25.0%")
      && partialHtml.includes("odds conditional on this pairing") && partialHtml.includes("Fate chances unavailable until this pairing is settled")
      && !partialHtml.includes("data-match-stake=");
  }
  check(oldOK, "cup stakes legacy/partial: missing fields offer no false fates or Bigcups; oldcards label stored odds and a25% pairing explains conditional odds/withheld fates");
  X.MATCHES = MATCHES; X.NEXT = NEXT;
}

// ---------------------------------------------------------------- per-world European entry
// Competition entry follows this world's cup/UEFA winners. Position distributions remain literal
// league places, so they cannot inherit European qualification bands in the new generation.
{
  X.RESULT = RESULT;
  const keys = ["ucl", "uel", "uecl"];
  const decode = (s) => s.replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&amp;/g, "&");
  const plain = (s) => decode(s.replace(/<[^>]*>/g, "")).trim();
  const attrs = (s) => Object.fromEntries([...s.matchAll(/([\w-]+)="([^"]*)"/g)].map((m) => [m[1], decode(m[2])]));
  const leagues = RESULT.leagues.filter((b) => b.qualification?.mode === "per_world");
  const off = [], sampleOff = [], outsideOff = [];
  let values = 0, lines = 0, sampleCells = 0, outsiders = 0, foreign = 0;
  for (const block of leagues) {
    const html = X.league(block), n = block.size || block.teams.length;
    const body = html.match(/<tbody>([\s\S]*?)<\/tbody>/)?.[1] || "";
    const rows = [...body.matchAll(/<tr\b[^>]*>([\s\S]*?)<\/tr>/g)];
    if (!html.includes('data-qualification-mode="per_world"') || !plain(html).includes("competition entry, including qualifying")
      || !plain(html).includes("EPS allocation held from last season") || rows.length !== block.teams.length
      || JSON.stringify(X.zonesOf(block)) !== JSON.stringify([[1,1,"good","Title"],[n-(block.relegated??3)+1,n,"bad","Rel"]])) off.push(`${block.competition}: entry legend/field detection/position bands`);
    for (const row of rows) {
      const team = attrs(row[1].match(/<td\b([^>]*data-team="[^"]*"[^>]*)>/)?.[1] || "")["data-team"];
      const source = block.teams.find((r) => r.team === team);
      const cells = [...row[1].matchAll(/<td\b([^>]*data-europe-fate="[^"]*"[^>]*)>([\s\S]*?)<\/td>/g)];
      if (!source || cells.length !== 3) { off.push(`${block.competition}/${team}: incomplete entry row`); continue; }
      for (const cell of cells) {
        values++;
        const a = attrs(cell[1]), p = source["p_" + a["data-europe-fate"]], shown = plain(cell[2]);
        if (!keys.includes(a["data-europe-fate"]) || a["data-europe-p"] !== String(p ?? "")
          || (p == null ? shown !== "—" : !Number.isFinite(parseFloat(shown)) || Math.abs(parseFloat(shown)/100-p) > .0005 + 1e-9)) off.push(`${block.competition}/${team}: displayed ${a["data-europe-fate"]} differs from entry chance`);
      }
    }
    for (const line of block.lines || []) {
      lines++;
      const want = line.place === 2 ? "Title" : line.place === n-(block.relegated??3)+1 ? `Survival (top ${line.place-1})` : `Top ${line.place-1} (league position)`;
      if (X.lineName(block,line.place) !== want) off.push(`${block.competition}: points line falsely implies qualification`);
    }
    for (const sample of RESULT.samples || []) {
      if (!Array.isArray(sample.leagues?.[block.competition])) continue;
      const rows = sample.leagues[block.competition];
      const known = keys.every((key) => Array.isArray(sample.europe?.[key]));
      if (!known || !X.sampleEuropeKnown(sample)) { sampleOff.push(`world${sample.world}: entry arrays missing`); continue; }
      const all = keys.flatMap((key) => sample.europe[key]);
      if (new Set(all).size !== all.length) sampleOff.push(`world${sample.world}: overlapping entries`);
      for (const row of rows) {
        sampleCells++;
        const team=row.team,fate=keys.filter(key=>sample.europe[key].includes(team)).join('/');
        if(X.sampleEurope(sample,team)!==fate)sampleOff.push(`${block.competition} world${sample.world}/${team}: retained sample entry differs`);
      }
    }
  }
  const topflight = new Set(RESULT.leagues.flatMap((b) => b.teams.map((t) => t.team)));
  for (const row of RESULT.europe?.teams || []) {
    if (topflight.has(row.team) || !keys.some((key) => row["p_"+key] > 0)) continue;
    outsiders++; foreign += row.association == null;
    const html = X.teamEuropeHtml(row.team), root = attrs(html.match(/<div\b([^>]*)>/)?.[1] || "");
    const spans = [...html.matchAll(/<span\b([^>]*data-europe-fate="[^"]*"[^>]*)>([\s\S]*?)<\/span>\s*<b>([\s\S]*?)<\/b>/g)];
    if (root["data-team-europe"] !== row.team || root["data-team-europe-scope"] !== (row.association == null ? "title_route" : "competition_entry")
      || spans.length !== 3 || (row.association == null && !plain(html).includes("domestic qualification not modeled"))) outsideOff.push(`${row.team}: missing/overstated outside-league route`);
    for (const span of spans) {
      const a = attrs(span[1]), value = row["p_" + a["data-europe-fate"]];
      if (a["data-europe-p"] !== String(value ?? "") || (value == null ? plain(span[3]) !== "—" : Math.abs(parseFloat(plain(span[3]))/100-value) > .0005 + 1e-9)) outsideOff.push(`${row.team}: outside-league entry value differs`);
    }
  }
  if (leagues.length) {
    check(leagues.length === 5 && values > 0 && lines > 0 && !off.length,
      `European entry: ${values} Overview cells equal world-entry probabilities; ${lines} points lines and 5 position tables retain literal league places`,off.slice(0,4).join("; "));
    check(sampleCells > 0 && !sampleOff.length,`European entry: ${sampleCells} sampled league cells show their own world's exclusive UCL/UEL/UECL entry`,sampleOff.slice(0,4).join("; "));
    check(outsiders > 0 && foreign > 0 && !outsideOff.length,`European entry: ${outsiders} outside-league team cards (${foreign} foreign title-only routes) preserve exact source probabilities and scope`,outsideOff.slice(0,4).join("; "));
  } else console.log("  skip    per-world European-entry UI identities (snapshot predates qualification metadata)");
  const first = RESULT.leagues[0];
  if (first) {
    const world = {...first,qualification:{mode:"per_world",scope:"competition_entry",season:RESULT.params.season+1,eps_policy:"previous_allocation"},teams:first.teams.map((r,i)=>i ? r : {...r,p_ucl:undefined,p_top4:.73,p_uel:.2,p_uecl:.1})};
    const legacy = {...world}; delete legacy.qualification;
    const worldResult = {...RESULT,leagues:RESULT.leagues.map((b)=>b===first?world:b)};
    X.RESULT = worldResult;
    const row = [...X.league(world).matchAll(/<tr>([\s\S]*?)<\/tr>/g)].map(m=>m[1])
      .find(row=>attrs(row.match(/<td\b([^>]*data-team="[^"]*"[^>]*)>/)?.[1]||"")["data-team"]===world.teams[0].team)||"";
    const cell = row.match(/<td\b[^>]*data-europe-fate="ucl"[^>]*>([\s\S]*?)<\/td>/)?.[1] || "";
    const oldZones = X.zonesOf(legacy), u=legacy.ucl_spots??4;
    const sample = (RESULT.samples || []).find((s)=>s.leagues?.[first.competition]);
    const noEurope = sample ? {...sample} : null;
    if (noEurope) delete noEurope.europe;
    const absentResult = {...RESULT,samples:noEurope?[noEurope]:[]}; X.RESULT = absentResult;
    X.RESULT = worldResult;
    check(plain(cell)==="—" && X.whatifNow(world.competition,"league",world.teams[0].team,"ucl")===null
      && X.whatifNow(world.competition,"league",world.teams[0].team,"euro")===null
      && oldZones.some((z)=>z[0]===1&&z[1]===u&&z[3]==="UCL") && !X.perWorldQualification(legacy)
      && !X.qualificationNote(legacy) && !X.sampleEuropeKnown(noEurope) && X.sampleEurope(noEurope,world.teams[0].team)===null
,
      "European entry guards: missing actual probabilities remain unknown despite p_top4; earlier v11 keeps old bands and offers no invented sample entry");
  }
  X.RESULT = RESULT;
}

// ---------------------------------------------------------------- mobile navigation and keyboard
// These nodes implement the small DOM surface used by accessibility and sorting. The behavior
// checks dispatch the page's own handlers; no network, browser executable or optional library.
{
  const savedDocument = globalThis.document, savedMouseEvent = globalThis.MouseEvent;
  const savedCSS = globalThis.CSS, savedRender = X.RENDER;
  const savedState = {tab:X.TAB,views:{...X.VIEWSEL},focus:X.FOCUS,page:X.TEAM_PAGE,match:X.MATCH_FOCUS,
    keyboard:X.KEYBOARD_MODE,last:X.LAST_FOCUS,requested:X.REQUESTED_FOCUS,teamOpener:X.TEAM_OPENER,matchOpener:X.MATCH_OPENER};
  let doc;
  class Node {
    constructor(tag, attrs = {}, text = "") {
      this.tagName = tag.toUpperCase(); this.parentElement = null; this.children = []; this.attrs = new Map();
      this.dataset = {}; this._text = text; this.clicks = 0; this.connected = true; this.hidden = false;
      this.style = {}; this.offsetWidth = 140; this.offsetHeight = 60;
      this.classList = {add:(...v)=>v.forEach((x)=>this.classes.add(x)),remove:(...v)=>v.forEach((x)=>this.classes.delete(x)),contains:(x)=>this.classes.has(x)};
      this.classes = new Set(); this.listeners = {};
      Object.entries(attrs).forEach(([key,value])=>this.setAttribute(key,value));
    }
    setAttribute(key,value) {
      this.attrs.set(key,String(value));
      if (key.startsWith("data-")) this.dataset[key.slice(5).replace(/-([a-z])/g,(_,c)=>c.toUpperCase())]=String(value);
      if (key==="class") this.classes=new Set(String(value).split(/\s+/).filter(Boolean));
      if (key==="id") this.id=String(value);
    }
    getAttribute(key) { const data=key.startsWith("data-")?key.slice(5).replace(/-([a-z])/g,(_,c)=>c.toUpperCase()):null; return data&&Object.hasOwn(this.dataset,data)?String(this.dataset[data]):this.attrs.get(key)??null; }
    hasAttribute(key) { return this.getAttribute(key)!==null; }
    removeAttribute(key) { this.attrs.delete(key); if(key.startsWith("data-")) delete this.dataset[key.slice(5).replace(/-([a-z])/g,(_,c)=>c.toUpperCase())]; }
    get attributes() { return [...this.attrs].map(([name,value])=>({name,value})); }
    get isConnected() { return this.connected; }
    get ownerDocument() { return doc; }
    get tabIndex() { return +(this.getAttribute("tabindex") ?? (this.matches("button,input,select,textarea,a[href],summary")?0:-1)); }
    set tabIndex(v) { this.setAttribute("tabindex",v); }
    get textContent() { return this._text+this.children.map((n)=>n.textContent).join(""); }
    set textContent(value) { this._text=String(value); }
    get cells() { return this.children.filter((n)=>n.matches("td,th")); }
    get rows() { return this.children.filter((n)=>n.tagName==="TR"); }
    getBoundingClientRect() { return {left:0,top:0,width:100,height:24,right:100,bottom:24}; }
    getClientRects() { return this.hidden?[]:[this.getBoundingClientRect()]; }
    appendChild(node) { if(node.parentElement) node.parentElement.children.splice(node.parentElement.children.indexOf(node),1); node.parentElement=this; this.children.push(node); return node; }
    append(...nodes) { nodes.forEach((node)=>this.appendChild(node)); }
    remove() { if(this.parentElement) this.parentElement.children.splice(this.parentElement.children.indexOf(this),1); this.connected=false; }
    matches(selectors) {
      return selectors.split(",").some((part)=> {
        part=part.trim(); if(!part) return false;
        const words=part.split(/\s+(?![^\[]*\])/); const last=words.pop();
        if(words.length) { let parent=this.parentElement; const ancestor=words.join(" "); while(parent&&!parent.matches(ancestor)) parent=parent.parentElement; if(!parent) return false; }
        const attrs=[...last.matchAll(/\[([\w-]+)(?:=["']?([^\]"']*)["']?)?\]/g)];
        const simple=last.replace(/\[[^\]]*\]/g,"");
        const tag=simple.match(/^[a-z][\w-]*/i)?.[0];
        if(tag&&this.tagName!==tag.toUpperCase()) return false;
        const id=simple.match(/#([\w-]+)/)?.[1]; if(id&&this.id!==id) return false;
        if([...simple.matchAll(/\.([\w-]+)/g)].some((m)=>!this.classes.has(m[1]))) return false;
        if(simple.includes(":disabled")&&!this.disabled) return false;
        return attrs.every((m)=>this.hasAttribute(m[1])&&(m[2]===undefined||this.getAttribute(m[1])===m[2].replace(/\\(.)/g,"$1")));
      });
    }
    closest(selector) { for(let node=this;node;node=node.parentElement) if(node.matches(selector)) return node; return null; }
    querySelectorAll(selector) { const out=[]; const visit=(node)=>{for(const child of node.children){if(child.matches(selector)) out.push(child);visit(child);}};visit(this);return out; }
    querySelector(selector) { return this.querySelectorAll(selector)[0]||null; }
    focus() { doc.activeElement=this; }
    click() { this.clicks++; this.dispatchEvent({type:"click",target:this,bubbles:true}); }
    addEventListener(type,fn) { (this.listeners[type] ||= []).push(fn); }
    removeEventListener(type,fn) { this.listeners[type]=(this.listeners[type]||[]).filter((listener)=>listener!==fn); }
    dispatchEvent(ev) { if(!ev.target) ev.target=this; if(!["focusin","focusout"].includes(ev.type)) this["on"+ev.type]?.(ev); for(const fn of this.listeners[ev.type]||[]) fn(ev); if(ev.bubbles&&this.parentElement) this.parentElement.dispatchEvent(ev); return true; }
    insertAdjacentHTML(_,markup) { if(markup.includes('class="arrow"')) this.appendChild(new Node("span",{class:"arrow"})); }
  }
  const body=new Node("body"), host=new Node("div",{id:"view"}); body.appendChild(host);
  doc={body,activeElement:body,querySelectorAll:(selector)=>body.querySelectorAll(selector),querySelector:(selector)=>selector==="body"?body:body.querySelector(selector),
    getElementById:(id)=>body.querySelector("#"+id),createElement:(tag)=>new Node(tag)};
  globalThis.document=doc;
  globalThis.CSS={...(savedCSS||{}),escape:(s)=>String(s).replace(/(["\\])/g,"\\$1")};
  if(!globalThis.MouseEvent) globalThis.MouseEvent=class {constructor(type,options={}){this.type=type;Object.assign(this,options);}};
  const event=(target,key,repeat=false)=>({target,key,repeat,prevented:false,stopped:false,preventDefault(){this.prevented=true;},stopPropagation(){this.stopped=true;}});
  try {
    const row=new Node("tr",{"data-match":"Alpha|Beta|2026-10-22"}),team=new Node("td",{class:"team","data-team":"Alpha"}),badge=new Node("img",{"data-team":"Alpha"});
    const opponent=new Node("td",{class:"team","data-team":"Beta"}); team.appendChild(badge); row.append(team,opponent); host.appendChild(row);
    const card=new Node("div",{class:"comp","data-comp":"English Premier League"}); host.appendChild(card);
    const chart=new Node("path",{"data-hl":"Alpha"}); host.appendChild(chart);
    const plainTeam=new Node("span",{"data-team":"Gamma"}); host.appendChild(plainTeam);
    const native=[new Node("button",{"data-team":"Native"}),new Node("select"),new Node("input"),new Node("textarea"),new Node("a",{href:"#"}),new Node("summary")];
    native.forEach((node)=>host.appendChild(node));
    const insideNative=new Node("span");native[0].appendChild(insideNative);
    const peerRow=new Node("tr"),peers=Array.from({length:5},()=>new Node("td",{"data-match":"One|Two|2026-10-23"}));peers.forEach((node)=>peerRow.appendChild(node));host.appendChild(peerRow);
    X.wireAccessibility(doc);
    const custom=[row,team,opponent,card,chart,plainTeam];
    chart.click=undefined; // SVG elements use the dispatchEvent fallback in real browsers.
    let actionOK=custom.every((node)=>node.tabIndex===0&&Boolean(node.getAttribute("role")))&&badge.tabIndex!==0&&peers.filter((node)=>node.tabIndex===0).length===1&&peers[0].tabIndex===0;
    let dispatched=0;
    for(const target of custom) {
      target.onclick=(ev)=>{if(ev.target===target)dispatched++;};
      for(const key of ["Enter"," "]) {const before=dispatched,ev=event(target,key);X.keyboardAction(ev);actionOK&&=dispatched===before+1&&ev.prevented;}
      for(const ev of [event(target,"Enter",true),event(target," ",true),event(target,"Tab"),event(target,"x")]) {const before=dispatched;X.keyboardAction(ev);actionOK&&=dispatched===before;}
    }
    const customDispatches=dispatched;
    let nativeOK=native.every((node)=>X.nativeControl(node))&&X.nativeControl(insideNative);
    for(const target of [...native,insideNative]) for(const key of ["Enter"," "]) {const ev=event(target,key),before=dispatched;X.keyboardAction(ev);nativeOK&&=dispatched===before&&!ev.prevented&&target.clicks===0;}
    let modalityOK=true,modeChanges=0;
    for(const target of native)for(const key of ["r","ArrowDown"]){
      X.KEYBOARD_MODE=false;const ev=event(target,key);X.markKeyboardMode(ev);modeChanges++;
      modalityOK&&=X.KEYBOARD_MODE&&!ev.prevented&&!ev.stopped&&target.clicks===0;
    }
    for(const key of ["Tab","Enter"," ","Escape","ArrowUp","ArrowLeft","ArrowRight","Home","End","PageUp","PageDown"]){
      X.KEYBOARD_MODE=false;X.markKeyboardMode(event(body,key));modeChanges++;modalityOK&&=X.KEYBOARD_MODE;
    }
    for(const ev of [event(native[1],"F1"),event(plainTeam,"r"),...["Control","Alt","Meta","Shift"].map(key=>event(native[1],key)),
      ...["ctrlKey","altKey","metaKey"].map(modifier=>({...event(native[1],"r"),[modifier]:true}))]){
      X.KEYBOARD_MODE=false;X.markKeyboardMode(ev);modalityOK&&=!X.KEYBOARD_MODE;
    }
    modalityOK&&=/window\.addEventListener\("keydown",\s*\(ev\)\s*=>\s*\{\s*markKeyboardMode\(ev\);[\s\S]*?\}, true\)/.test(js);
    check(actionOK&&customDispatches===12&&nativeOK&&modalityOK&&modeChanges===23,"keyboard: 6 custom targets activate once; native controls never double-fire; 23 typeahead/navigation events enable keyboard focus after pointer use, while modified typing/unrelated keys and duplicate targets are ignored");

    // Chrome does not wire arbitrary onfocusin/onfocusout properties to bubbling focus events.
    // Dispatch through registered listeners so a mouse-only tooltip cannot pass this check.
    const tipRoot=new Node("div"),marks=[new Node("circle",{"data-team":"Alpha","data-tip":"<b>Alpha</b> — xG 1.23"}),new Node("path",{"data-hl":"Beta","data-tip":"<b>Beta</b> — 27.4%"})];
    marks.forEach((mark)=>tipRoot.appendChild(mark));host.appendChild(tipRoot);
    X.attachTips(tipRoot);X.attachTips(tipRoot);
    const tip=doc.getElementById("vtip");
    let tipsOK=Boolean(tip)&&(tipRoot.listeners.focusin||[]).length===1&&(tipRoot.listeners.focusout||[]).length===1;
    for(const mark of marks) {
      mark.dispatchEvent({type:"focusin",target:mark,bubbles:true});
      tipsOK&&=tip.hidden===false&&tip.innerHTML===mark.getAttribute("data-tip")&&tip.style.left==="64px"&&tip.style.top==="26px";
      mark.dispatchEvent({type:"focusout",target:mark,bubbles:true});tipsOK&&=tip.hidden===true;
    }
    const unrelated=new Node("button");tipRoot.appendChild(unrelated);unrelated.dispatchEvent({type:"focusin",target:unrelated,bubbles:true});tipsOK&&=tip.hidden===true;
    tipRoot.onmousemove({target:marks[0],clientX:90,clientY:80});tipsOK&&=tip.hidden===false&&tip.innerHTML===marks[0].getAttribute("data-tip");
    tipRoot.onmouseleave();tipsOK&&=tip.hidden===true;
    check(tipsOK,"keyboard tooltips: 2 SVG marks show exact shared tooltip content on registered focus events and hide on blur; rebinding keeps1 listener per type, unrelated focus and pointer hover remain correct");

    const table=new Node("table",{class:"sortable"}),head=new Node("thead"),headRow=new Node("tr"),tbody=new Node("tbody");
    const nameHead=new Node("th",{"data-sort":"1"},"Team"),valueHead=new Node("th",{"data-sort":"1","data-first":"asc"},"Value");
    headRow.append(nameHead,valueHead);head.appendChild(headRow);table.append(head,tbody);table.tBodies=[tbody];table.tHead=head;host.appendChild(table);
    for(const [name,value] of [["Beta",".95"],["Gamma","—"],["Alpha",".2"]]) {const r=new Node("tr");r.append(new Node("td",{},name),new Node("td",{"data-v":value},value==="—"?value:String(+value*100)+"%"));tbody.appendChild(r);}
    X.wireAccessibility(doc);
    const names=()=>tbody.rows.map((r)=>r.cells[0].textContent).join(",");
    valueHead.onclick=()=>X.sortTable(valueHead);nameHead.onclick=()=>X.sortTable(nameHead);
    const sortEnter=event(valueHead,"Enter"),sortSpace=event(valueHead," "),sortOther=event(nameHead,"Enter");
    X.keyboardAction(sortEnter);let sortOK=sortEnter.prevented&&valueHead.tabIndex===0&&names()==="Alpha,Beta,Gamma"&&valueHead.getAttribute("aria-sort")==="ascending";
    X.keyboardAction(sortSpace);sortOK&&=sortSpace.prevented&&names()==="Beta,Alpha,Gamma"&&valueHead.getAttribute("aria-sort")==="descending";
    X.keyboardAction(sortOther);sortOK&&=sortOther.prevented&&names()==="Gamma,Beta,Alpha"&&nameHead.getAttribute("aria-sort")==="descending"&&!['ascending','descending'].includes(valueHead.getAttribute("aria-sort"));
    check(sortOK,"keyboard sorting: Enter/Space on2 headers sort3 rows by raw values, missing-last and first-direction; reverse/new heading update aria-sort without multiple active announcements");

    const control=new Node("button",{"data-dw":"1m"});host.appendChild(control);X.wireAccessibility(doc);
    X.KEYBOARD_MODE=true;X.REQUESTED_FOCUS=null;const key=X.focusKey(control);X.LAST_FOCUS=key;
    control.remove();const replacement=new Node("button",{"data-dw":"1m"});host.appendChild(replacement);doc.activeElement=body;X.wireAccessibility(doc);
    let focusOK=Boolean(key)&&X.focusKey(replacement)===key&&doc.activeElement===replacement;
    const independent=new Node("input",{id:"independent"});host.appendChild(independent);X.wireAccessibility(doc);independent.focus();
    focusOK&&=X.restoreFocus(key)===false&&doc.activeElement===independent;
    X.REQUESTED_FOCUS=key;focusOK&&=X.restoreFocus()===true&&doc.activeElement===replacement&&X.REQUESTED_FOCUS===null;
    X.KEYBOARD_MODE=false;doc.activeElement=body;focusOK&&=X.restoreFocus(key)===false&&doc.activeElement===body;
    X.KEYBOARD_MODE=true;focusOK&&=X.restoreFocus("missing-opener")===false;
    const select=new Node("select",{id:"mobile-nav"});body.appendChild(select);X.wireAccessibility(doc);
    focusOK&&=X.focusKey(select)==="id:mobile-nav";
    check(focusOK,"keyboard focus: same logical pill regains focus after replacement; active controls/pointer mode are preserved, requested focus wins, missing opener is safe and native picker has a stable key");

    let renders=[];X.RENDER=(push=false)=>{renders.push(push);};X.TEAM_OPENER=key;X.MATCH_OPENER="id:independent";
    X.FOCUS="Alpha";X.TEAM_PAGE=true;X.MATCH_FOCUS="Alpha|Beta|2026-10-22";X.REQUESTED_FOCUS=null;
    const firstEscape=event(independent,"Escape");let escapeOK=X.handleEscape(firstEscape)===true&&X.MATCH_FOCUS===null&&X.FOCUS==="Alpha"&&X.TEAM_PAGE&&X.REQUESTED_FOCUS==="id:independent"&&firstEscape.prevented&&firstEscape.stopped&&renders.length===1;
    const secondEscape=event(independent,"Escape");escapeOK&&=X.handleEscape(secondEscape)===true&&X.FOCUS===null&&!X.TEAM_PAGE&&X.REQUESTED_FOCUS===key&&secondEscape.prevented&&renders.length===2;
    const idle=event(independent,"Escape"),repeat=event(independent,"Escape",true);escapeOK&&=X.handleEscape(idle)===false&&X.handleEscape(repeat)===false&&renders.length===2;
    check(escapeOK,"keyboard Escape: match closes before the underlying full team page; second Escape closes team, each restores its own opener, idle/repeated keys make no extra render");

    X.RESULT=RESULT;X.PLAYERS=PLAYERS;X.PLAYERS_FOR=RESULT;X.PLAYERS_STATUS=PLAYERS?"ready":"missing";
    const groups=X.tabGroups(X.presentComps()),extras=[X.MOVERS,X.PERFORMANCE,X.TIME_MACHINE,X.FORECAST_LAB,...((RESULT.version||1)>=10?[X.BIG]:[]),...(RESULT.trophies?[X.TROPHIES]:[]),...(RESULT.ratings?[X.RATINGS,X.ALLVIZ]:[])];
    const expected=[];
    const extraGroups=[["Explore",[X.ALLVIZ,X.TIME_MACHINE,X.FORECAST_LAB]]];
    for(const [group,comps] of [...groups,...extraGroups]) for(const tab of comps) {
      const available=extras.includes(tab)?[["overview",""]]:X.viewsFor(tab),views=available.length?available:[["overview","Overview"]];
      for(const [view] of views) expected.push({group,tab,view});
    }
    const decode=(text)=>text.replace(/&quot;/g,'"').replace(/&#39;/g,"'").replace(/&amp;/g,"&");
    let choices=0,navOK=expected.length>0;
    for(const wanted of expected) {
      const options=X.mobileNavOptions(),option=options.find((o)=>o.tab===wanted.tab&&o.view===wanted.view),before=renders.length;
      if(!option){navOK=false;continue;}
      X.FOCUS="Alpha";X.TEAM_PAGE=true;X.MATCH_FOCUS="Alpha|Beta|2026-10-22";
      const changed=X.chooseMobileNav(option.value);choices++;
      const selected=X.mobileNavOptions().filter((o)=>o.selected);
      navOK&&=changed===true&&X.TAB===wanted.tab&&!X.TEAM_PAGE&&X.MATCH_FOCUS===null&&renders.length===before+1&&renders.at(-1)===true&&selected.length===1&&selected[0].value===option.value;
    }
    const options=X.mobileNavOptions(),markup=X.mobileNavHtml(),domOptions=[...markup.matchAll(/<option\b([^>]*)>([\s\S]*?)<\/option>/g)];
    const attr=(text)=>Object.fromEntries([...text.matchAll(/([\w-]+)="([^"]*)"/g)].map((m)=>[m[1],decode(m[2])]));
    navOK&&=options.length===expected.length&&new Set(options.map((o)=>o.value)).size===expected.length&&JSON.stringify(options.map(({group,tab,view})=>({group,tab,view})))===JSON.stringify(expected)
      &&domOptions.length===options.length&&domOptions.every((m,i)=>attr(m[1]).value===options[i].value&&/\bselected\b/.test(m[1])===options[i].selected)
      &&JSON.stringify([...markup.matchAll(/<optgroup\b[^>]*label="([^"]*)"/g)].map((m)=>decode(m[1])))===JSON.stringify([...new Set(expected.map((o)=>o.group))]);
    const before=renders.length;navOK&&=X.chooseMobileNav("tab=does-not-exist&view=overview")===false&&renders.length===before;
    check(navOK,`mobile navigation: ${choices} exact competition/view choices across ${new Set(expected.map((o)=>o.tab)).size} tabs preserve desktop groups, selected state, valid views and route transitions; invalid choices ignored`);
  } finally {
    globalThis.document=savedDocument; globalThis.CSS=savedCSS;
    if(savedMouseEvent===undefined) delete globalThis.MouseEvent; else globalThis.MouseEvent=savedMouseEvent;
    X.RENDER=savedRender; X.TAB=savedState.tab; Object.assign(X.VIEWSEL,savedState.views);
    X.FOCUS=savedState.focus; X.TEAM_PAGE=savedState.page; X.MATCH_FOCUS=savedState.match;
    X.KEYBOARD_MODE=savedState.keyboard; X.LAST_FOCUS=savedState.last; X.REQUESTED_FOCUS=savedState.requested;
    X.TEAM_OPENER=savedState.teamOpener; X.MATCH_OPENER=savedState.matchOpener;
  }
}

// Movers routes keep only the selected category and preserve the shared change window.
{
  const originalLocation=globalThis.location,originalHistory=globalThis.history,originalDraw=X.DRAW_MOVERS;
  const state={tab:X.TAB,mode:X.MOVERSEL,window:X.DWIN,focus:X.FOCUS,page:X.TEAM_PAGE,match:X.MATCH_FOCUS,views:{...X.VIEWSEL}};
  let draws=0;const pushes=[];
  globalThis.location={hash:""};globalThis.history={pushState:(_,__,hash)=>{pushes.push(hash);location.hash=hash;},replaceState:(_,__,hash)=>{location.hash=hash;}};
  X.DRAW_MOVERS=()=>{draws++;};location.hash="#tab=Movers";X.applyHash();X.FOCUS=null;X.TEAM_PAGE=false;X.MATCH_FOCUS=null;
  let routeOK=true,roundTrips=0;
  try {
    for(const mode of ["title","europe","survival","cups"]) {
      X.DWIN="1m";
      const before=draws;if(!X.chooseMover(mode)){routeOK=false;continue;}
      const params=new URLSearchParams(location.hash.slice(1));
      routeOK&&=X.DWIN==="1m"&&draws===before+1&&params.get("tab")===X.ALLVIZ&&params.get("viz")==="changes"&&params.get("category")===(mode==="title"?null:mode)&&params.get("dw")==="1m";
      X.MOVERSEL="invalid";X.DWIN="season";X.applyHash();roundTrips++;
      routeOK&&=X.MOVERSEL===mode&&X.DWIN==="1m";
    }
    for(const hash of ["#tab=Movers","#tab=Movers&category=invalid"]) {location.hash=hash;X.MOVERSEL="cups";X.applyHash();routeOK&&=X.MOVERSEL==="title";}
    const before=draws,oldHash=location.hash;routeOK&&=X.chooseMover("invalid")===false&&draws===before&&location.hash===oldHash;
    routeOK&&=X.moversData("invalid").id==="title"&&/data-movers="title"/.test(X.moversHtml("invalid"));
    X.TAB=RESULT.leagues[0].competition;X.MOVERSEL="cups";X.writeHash(false);routeOK&&=!new URLSearchParams(location.hash.slice(1)).has("category");
    for(const dates of [[],[RESULT.source?.date||RESULT.as_of]]) {
      X.HISTORY={...HISTORY,dates};X.MOVERSEL="europe";
      const html=X.moversHtml(),pills=[...html.matchAll(/<button\b([^>]*data-opt="movers"[^>]*)>/g)];
      routeOK&&=!html.includes("data-movers=")&&pills.length===4&&html.includes("changes need an earlier snapshot");
    }
    check(routeOK&&roundTrips===4&&pushes.length===4,"movers routes: all4 categories round-trip in the URL without changing1M; default/invalid categories select Title, other tabs omit category, and0/1-snapshot views retain controls without invented rows");
  } finally {
    X.DRAW_MOVERS=originalDraw;X.TAB=state.tab;X.MOVERSEL=state.mode;X.DWIN=state.window;X.FOCUS=state.focus;X.TEAM_PAGE=state.page;X.MATCH_FOCUS=state.match;Object.assign(X.VIEWSEL,state.views);X.HISTORY=HISTORY;
    if(originalLocation===undefined)delete globalThis.location;else globalThis.location=originalLocation;
    if(originalHistory===undefined)delete globalThis.history;else globalThis.history=originalHistory;
  }
}

// ---------------------------------------------------------------- compact chart controls and Matchcard hierarchy
{
  const decode=s=>s.replace(/&quot;/g,'"').replace(/&#39;/g,"'").replace(/&lt;/g,"<").replace(/&gt;/g,">").replace(/&amp;/g,"&");
  const attrs=s=>Object.fromEntries([...s.matchAll(/([\w-]+)="([^"]*)"/g)].map(m=>[m[1],decode(m[2])]));
  const saved={opts:{...X.VIZOPT},settings:X.VIZ_SETTINGS_OPEN,highlights:X.VIZ_HIGHLIGHTS_OPEN,window:X.DWIN,tab:X.TAB};
  const location0=globalThis.location,history0=globalThis.history;
  const off=[];let pickers=0,options=0,charts=0,settings=0;
  const expected={league:[['Strength',['ad','rt','ev']],['This season',['xp','gx','sq','fm']],['Projection',['pr','fp','ri']],['Team performance',['trajectory','expectation','quality']],['History',['tmbridge','tmfates','tmstrength']],['Race Room',['rivals','entryroutes','timing']]],
    uefa:[['Strength',['ad','rt','ev']],['This season',['xp','gx','sq','fm']],['Projection',['pr','fp','ri']],['Knockouts',['ko','nt','kf','os','sw']]],cup:[['Knockouts',['ko','nt','kf','os','sw']]]};
  const selects=markup=>[...markup.matchAll(/<select\b([^>]*)>([\s\S]*?)<\/select>/g)];
  const checkControls=(markup,tag)=>{
    const panels=[...markup.matchAll(/<details\b([^>]*data-chart-options="1"[^>]*)>/g)];
    settings+=panels.length;
    if(panels.length>1||panels.some(m=>/\bopen(?:\s|>|$)/.test(m[1])))off.push(`${tag}: optional settings not one closed disclosure`);
    for(const m of selects(markup)){
      const a=attrs(m[1]);if(!a['data-chart-opt']&&!a['data-chart-window'])continue;
      options++;
      const choices=[...m[2].matchAll(/<option\b([^>]*)>/g)];
      if(!a.id||!markup.includes(`<label for="${a.id}">`)||!choices.length||choices.filter(o=>/\bselected\b/.test(o[1])).length!==1)off.push(`${tag}: unlabeled/ambiguous native setting`);
      const selected=attrs(choices.find(o=>/\bselected\b/.test(o[1]))?.[1]||'').value;
      const want=a['data-chart-opt']?String(X.VIZOPT[a['data-chart-opt']]):X.VIZOPT.move?X.dwin()?.key:'none';
      const deferred=['rivalTeam','rivalOpponent','routeTeam','timingRound'].includes(a['data-chart-opt'])&&want==='';
      if(!deferred&&selected!==want)off.push(`${tag}: ${a['data-chart-opt']||'window'} selects ${selected} vs ${want}`);
    }
    if(/data-opt="(?:src|metric|marks|gside|gmeas|sqside|fm|prgap|lsm|rim)"/.test(markup))off.push(`${tag}: old chart-setting pills remain`);
  };
  try{
    X.VIZ_SETTINGS_OPEN=false;X.VIZ_HIGHLIGHTS_OPEN=false;X.VIZOPT.move=false;X.VIZOPT.src='model';
    for(const [kind,blocks] of [['league',RESULT.leagues],['uefa',RESULT.uefa],['cup',RESULT.cups||[]]]){
      const groups=X.vizGroups(kind),want=expected[kind];
      if(JSON.stringify(groups.map(([name,items])=>[name,items.map(([key])=>key)]))!==JSON.stringify(want))off.push(`${kind}: group/chart availability changed`);
      for(const pick of groups.flatMap(([,v])=>v).map(([key])=>key)){
        const markup=X.chartPickerHtml(groups,pick), select=selects(markup);
        pickers++;
        const choices=[...markup.matchAll(/<option\b([^>]*)>([\s\S]*?)<\/option>/g)],chosen=choices.filter(o=>/\bselected\b/.test(o[1]));
        if(select.length!==1||attrs(select[0][1])['data-chart-picker']!=='1'||(markup.match(/<optgroup\b/g)||[]).length!==groups.length
          ||JSON.stringify(choices.map(o=>attrs(o[1]).value))!==JSON.stringify(want.flatMap(([,keys])=>keys))||chosen.length!==1||attrs(chosen[0][1]).value!==pick)off.push(`${kind}/${pick}: chart select loses a group/option/selection`);
      }
      for(const block of blocks)for(const [,picks]of groups)for(const [pick]of picks){
        const g=(kind==='league'?GWD?.leagues:GWD?.phases)?.[block.competition]||null;
        const paths=(kind==='cup'?PATHSD?.cups:PATHSD?.competitions)?.[block.competition]||null;
        charts++;checkControls(X.vizHtml(block,kind,pick,g,paths),`${block.competition}/${pick}`);
      }
    }
    const all=X.chartPickerHtml([['Across Europe',X.ALLVIZ_LIST]],X.ALLVIZ_LIST[1][0],'all-chart-select');
    if(selects(all).length!==1||(all.match(/<option\b/g)||[]).length!==9||!all.includes('id="all-chart-select"'))off.push('all-competition picker loses chart options');
    check(pickers===Object.values(expected).reduce((n,groups)=>n+groups.reduce((s,[,keys])=>s+keys.length,0),0)&&charts>0&&settings>0&&options>0&&!off.length,`chart controls: ${pickers+1} grouped native pickers preserve all league/phase/cup/Europe charts; ${charts} rendered charts keep ${options} labeled selected settings in closed optional panels`,off.slice(0,5).join('; '));
    const chips='<button data-hl="Alpha">Alpha</button><button data-hl="Beta">Beta</button>';
    const closed=X.chartHighlightsHtml(chips,2);X.VIZ_HIGHLIGHTS_OPEN=true;const opened=X.chartHighlightsHtml(chips,2);
    let controlsOK=!/<details\b[^>]*\bopen\b/.test(closed)&&/<details\b[^>]*\bopen\b/.test(opened)&&closed.includes(chips)&&opened.includes(chips);
    X.VIZ_SETTINGS_OPEN=false;const closedSettings=X.chartSettingsHtml(X.chartOpt('src',[['model','Model'],['real','Season']],'model'));
    X.VIZ_SETTINGS_OPEN=true;const openSettings=X.chartSettingsHtml(X.chartOpt('src',[['model','Model'],['real','Season']],'model'));
    controlsOK&&=!/<details\b[^>]*\bopen\b/.test(closedSettings)&&/<details\b[^>]*\bopen\b/.test(openSettings)&&X.chartSettingsHtml('')==='';
    let redraw=0,hashWrites=0,moved=null;
    globalThis.location={hash:''};globalThis.history={replaceState(){hashWrites++;},pushState(){hashWrites++;}};X.TAB=RESULT.leagues[0].competition;
    const opt={dataset:{chartOpt:'prgap'},value:'true'},windowSelect={value:'none'},details={open:false,isConnected:true};
    const body={querySelectorAll:s=>s==='select[data-chart-opt]'?[opt]:s==='select[data-chart-window]'?[windowSelect]:[],querySelector:()=>details};
    const slot=mk('chart-settings-slot'),oldReplace=slot.replaceChildren;slot.replaceChildren=(...nodes)=>{moved=nodes;};
    X.wireChartSettings(body,()=>redraw++);opt.onchange();controlsOK&&=X.VIZOPT.prgap===true;
    opt.value='false';opt.onchange();controlsOK&&=X.VIZOPT.prgap===false;
    opt.value='custom';opt.onchange();controlsOK&&=X.VIZOPT.prgap==='custom';
    windowSelect.onchange();controlsOK&&=X.VIZOPT.move===false;
    const window=X.windowsOf()[0];if(window){windowSelect.value=window.key;windowSelect.onchange();controlsOK&&=X.DWIN===window.key&&X.VIZOPT.move===true;}
    details.open=false;details.ontoggle();controlsOK&&=X.VIZ_SETTINGS_OPEN===false;
    details.open=true;details.ontoggle();controlsOK&&=X.VIZ_SETTINGS_OPEN===true&&moved?.[0]===details;
    slot.replaceChildren=oldReplace;
    const expandedRule=html.match(/#chart-settings-slot:has\(>\.chart-options\[open\]\)\s*\{([^}]+)\}/)?.[1]||'';
    controlsOK&&=/flex\s*:\s*1\s+1\s+100%/.test(expandedRule)&&/width\s*:\s*100%/.test(expandedRule);
    check(controlsOK&&redraw===4+(window?1:0)&&hashWrites===1+(window?1:0),'chart control events: native string/boolean settings and shared-window changes redraw once; disclosure/highlights retain state and expanded options span the full toolbar row');
    X.VIZOPT.src='real';const real=X.vizHtml(RESULT.leagues[0],'league','ad',null,null);
    controlsOK=!real.includes('data-chart-window');
    X.VIZOPT.src='model';const model=X.vizHtml(RESULT.leagues[0],'league','ad',null,null);
    controlsOK&&=model.includes('data-chart-window')===Boolean(X.dwin());
    check(controlsOK,'chart field guards: tails are offered only for model strength with a comparable history window; season xG never invents movement controls');
  }finally{
    Object.assign(X.VIZOPT,saved.opts);X.VIZ_SETTINGS_OPEN=saved.settings;X.VIZ_HIGHLIGHTS_OPEN=saved.highlights;X.DWIN=saved.window;X.TAB=saved.tab;
    if(location0===undefined)delete globalThis.location;else globalThis.location=location0;
    if(history0===undefined)delete globalThis.history;else globalThis.history=history0;
  }
  let cards=0,retained=0;const cardOff=[];
  for(const entry of [...X.matchFixtures().filter(e=>!e.f.result),...X.matchFixtures().filter(e=>e.f.result).slice(0,10)]){
    const markup=X.matchCardHtml(entry),fold=markup.match(/<details\b([^>]*data-match-support="1"[^>]*)>([\s\S]*?)<\/details>/);
    cards++;
    if(!fold||/\bopen(?:\s|>|$)/.test(fold[1])){cardOff.push(`${X.matchKey(entry.f)}: support not initially collapsed`);continue;}
    const support=fold[2];
    retained+=(support.match(/data-match-recent=/g)||[]).length+(support.match(/data-match-rating=/g)||[]).length+(support.match(/data-match-h2h=/g)||[]).length;
    if((support.match(/data-match-recent=/g)||[]).length!==2||(support.match(/data-match-rating=/g)||[]).length!==2||(support.match(/data-match-h2h=/g)||[]).length!==1||support.includes('data-match-hda=')||support.includes('data-match-stake='))cardOff.push(`${X.matchKey(entry.f)}: support lost history or swallowed primary odds/stakes`);
  }
  check(cards>0&&retained===cards*5&&!cardOff.length,`match hierarchy: ${cards} cards keep primary odds/stakes visible and all ${retained} form/rating/h2h sections inside one initially collapsed disclosure`,cardOff.slice(0,3).join('; '));
  const fixture={home:'Heat Alpha',away:'Heat Beta',kickoff:'2026-11-01',ladder:{h1:0,d:1,a1:0},stakes:[[[0,null,.4],[.9,null,0]],[[1,null,0],[0,null,1]]],score_basis:'90min'};
  const entry={f:fixture,keys:['title','down'],competition:RESULT.leagues[0].competition,kind:'league'},heatOff=[];let heatCells=0;
  for(const home of [true,false]){
    const markup=X.matchStakesHtml(entry,home),rows=[...markup.matchAll(/<tr\b([^>]*data-match-stake="[^"]*"[^>]*)>([\s\S]*?)<\/tr>/g)];
    for(const row of rows){const ra=attrs(row[1]),key=ra['data-match-stake'].split('|')[1],i=entry.keys.indexOf(key),want=[...fixture.stakes[home?0:1][i]];if(!home)want.reverse();
      const cells=[...row[2].matchAll(/<td\b([^>]*data-stake-p="[^"]*"[^>]*)>([\s\S]*?)<\/td>/g)];
      if(cells.length!==3)heatOff.push(`${key}: missing heat cells`);
      cells.forEach((cell,j)=>{heatCells++;const a=attrs(cell[1]),v=want[j];if(a['data-stake-good']!==(key==='down'?'low':'high')||a['data-stake-p']!==(v==null?'':String(v))||!(v==null?cell[2].includes('—'):cell[2].includes((v*100).toFixed(1)+'%'))||a.style!==`--stake-fill:${v==null?0:Math.round(v*24)}%`)heatOff.push(`${key}/${j}: wrong direction/zero/null value`);});
    }
  }
  check(heatCells===12&&!heatOff.length,'match stake surfaces: 12 home/away cells preserve values/orientation; relegation is lower-is-better, zero remains0.0% and unknown remains—',heatOff.join('; '));
}

// The contrast oracle reads the actual CSS palette and the rendered inline colors independently.
{
  const css=html.match(/<style>([\s\S]*?)<\/style>/)?.[1]||'';
  const panels=[...css.matchAll(/--panel:\s*(#[0-9a-f]{6})\s*;/gi)].map(m=>m[1]).slice(0,2);
  const fills=[...css.matchAll(/--heat:\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*;/g)].map(m=>m.slice(1).map(Number)).slice(0,2);
  const rgb=h=>[1,3,5].map(i=>parseInt(h.slice(i,i+2),16));
  const luminance=c=>c.reduce((s,v,i)=>{v/=255;return s+[.2126,.7152,.0722][i]*(v<=.04045?v/12.92:((v+.055)/1.055)**2.4);},0);
  let min=Infinity,covered=0;const off=[];
  if(panels.length!==2||fills.length!==2)off.push('missing actual dark/light CSS palette');
  else for(let i=0;i<=1000;i++){
    const style=X.heatStyle(i/1000),percent=+(style.match(/\) ([\d.]+)%,var\(--panel\)/)?.[1]||NaN)/100;
    if(!style.startsWith('background:color-mix(in srgb,rgb(var(--heat))')||!Number.isFinite(percent)) {off.push(`alpha${i}: nonopaque/wrong palette fill`);continue;}
    for(const [theme,index]of [['dark',0],['light',1]]){
      const color=style.match(new RegExp(`--heat-${theme}-ink:(#[0-9a-f]+)`,'i'))?.[1];
      if(!['#fff','#000'].includes(color)){off.push(`${theme}/${i}: unsupported foreground`);continue;}
      const background=rgb(panels[index]).map((v,j)=>v*(1-percent)+fills[index][j]*percent),L=luminance(background),text=color==='#fff'?1:0;
      const contrast=(Math.max(L,text)+.05)/(Math.min(L,text)+.05);min=Math.min(min,contrast);covered++;
      if(contrast<4.5)off.push(`${theme}/${i}: contrast ${contrast.toFixed(3)}`);
    }
  }
  check(covered===2002&&!off.length,`heat contrast: ${covered} dark/light fills use actual opaque CSS colors with at least4.5:1 text contrast (minimum${min.toFixed(3)}:1)`,off.slice(0,4).join('; '));
  let parity=true,values=0;
  for(const p of [0,.0001,.005,.05,.2,.5,.9,1]){
    const tip=X.heatTip(p,'raw test'),alpha=.07+.93*p**.55;
    if(p===0)parity&&=tip.includes('class="heat z"')&&tip.includes('·')&&!tip.includes('style=');
    else parity&&=tip.includes(`style="${X.heatStyle(alpha)}"`);
    for(const byPts of [false,true]){
      const n={team:'A',opponent:'B',isHome:true,w:p,d:(1-p)/2,l:(1-p)/2},v=byPts?(3*n.w+n.d)/3:n.w;
      const run=X.runInCell(n,[],byPts);values++;
      parity&&=run.includes(`style="${X.heatStyle(.07+.93*v**.55)}"`)&&run.includes('data-ri="A|B|');
    }
  }
  parity&&=X.heatStyle(-.5)===X.heatStyle(0)&&X.heatStyle(1.5)===X.heatStyle(1);
  check(parity&&values===16,'heat scales: 8 probability cells preserve zero-dot/precision semantics; 16 run-in win/points cells share identical fill/ink mapping and clamp to valid opacity');
}

// Column profiles are presentation only. Compare rendered cells to All columns AND directly
// to the stored forecast, so a common renderer error cannot make the parity check pass.
{
  const savedProfile = X.COLUMN_PROFILE;
  const strip = s => s.replace(/<[^>]*>/g, "").trim();
  const decode = s => s.replace(/&quot;/g,'"').replace(/&amp;/g,'&').replace(/&lt;/g,'<');
  const cells = (markup, tag) => [...markup.matchAll(new RegExp(`<${tag}\\b([^>]*)>([\\s\\S]*?)<\\/${tag}>`, 'g'))].map(m => ({
    key: m[1].match(/data-column="([^"]*)"/)?.[1], hidden: /\bhidden\b/.test(m[1]), attrs: m[1], text: strip(m[2]), html: m[2]}));
  const tableRows = markup => [...markup.matchAll(/<tr>([\s\S]*?)<\/tr>/g)].slice(1).map(m => cells(m[1], 'td'));
  let pairs = 0, visible = 0, numeric = 0, helps = 0, profilesOK = true, payloadOK = true, evidenceOK = true;
  for (const [kind, blocks, draw] of [['league', RESULT.leagues, X.league], ['uefa', RESULT.uefa, X.uefa]]) for (const block of blocks) {
    X.COLUMN_PROFILE='all';
    const all = tableRows(draw(block)), columns=X.overviewColumns(block,kind), keys=columns.map(c=>c.key);
    const defaultPlaces=all.map(r=>Number(r.find(c=>c.key==='pos')?.text)).filter(Number.isFinite);
    profilesOK &&= !keys.includes('pos') || (keys[0]==='pos' && defaultPlaces.length===all.length && defaultPlaces.every((p,i)=>p===i+1));
    profilesOK &&= keys.length===new Set(keys).size && all.length===block.teams.length && all.length>0;
    for (const [profile] of X.COLUMN_PROFILES) {
      X.COLUMN_PROFILE=profile;
      const markup=draw(block), heads=cells(markup.match(/<thead>([\s\S]*?)<\/thead>/)[1],'th'), rows=tableRows(markup);
      profilesOK &&= rows.length===all.length && heads.length===keys.length && ['pos','rank'].includes(heads[0].key) && heads[1].key==='team' && !heads[0].hidden && !heads[1].hidden;
      const expected=profile==='all'?keys:kind==='league'?{
        forecast:['team','pts','pos','xpts','xpos','p_win','delta','ucl','ucl_delta','uel','uel_delta','uecl','uecl_delta','rel','rel_delta'], next:['team','pos','pl','pts','next5','next_opponent','next_w','next_d','next_l','next_cs']
      }[profile]:{
        forecast:['team','pts','pos','xpts','xpos','top8','mid','out','p_r16','p_qf','p_sf','p_f','p_win','delta'], next:['team','pos','pl','pts','next5','next_opponent','next_w','next_d','next_l','next_cs']
      }[profile];
      profilesOK &&= JSON.stringify(heads.filter(h=>!h.hidden).map(h=>h.key))===JSON.stringify(keys.filter(k=>k==='rank'||expected.includes(k)));
      for(let i=0;i<rows.length;i++) {
        pairs++;
        profilesOK &&= rows[i].length===heads.length && rows[i].every((c,j)=>c.key===heads[j].key&&c.hidden===heads[j].hidden&&c.html===all[i][j].html);
        const team=decode(rows[i].find(c=>c.key==='team').attrs.match(/data-team="([^"]*)"/)[1]);
        const source=block.teams.find(t=>t.team===team);
        for(const c of rows[i].filter(c=>!c.hidden)) {
          visible++;
          const value=({pts:source.now?.pts,pl:source.now?.pl,xpts:source.mean_pts,xpos:source.mean_pos??source.mean_seed,p_win:source.p_win,top8:source.p_top8,out:source.p_out,mid:source.p_mid??(source.p_top8==null||source.p_out==null?null:1-source.p_top8-source.p_out),ucl:source.p_ucl??(!X.perWorldQualification(block)?source.p_top4:null),uel:source.p_uel,uecl:source.p_uecl,rel:source.p_releg,p_r16:source.p_r16,p_qf:source.p_qf,p_sf:source.p_sf,p_f:source.p_f})[c.key];
          if(Number.isFinite(value)) {
            const isPct=!['pts','pl','xpts','xpos'].includes(c.key), shown=c.text==='·'?0:Number.parseFloat(c.text);
            // UEFA's heat renderer omits numbers below 0.05%; blank remains a valid tiny value.
            payloadOK &&= c.text===''&&isPct ? value*100<.05 : Math.abs(shown-value*(isPct?100:1)) <= .050001;
            numeric++;
          }
        }
      }
    }
    for(const c of columns.filter(c=>['xpts','p_win','pts','ucl','top8'].includes(c.key))) {
      const markup=X.metricEvidenceHtml(block,c);
      const attrs=markup.match(/<dl\b([^>]*)>/)[1], num=key=>Number(attrs.match(new RegExp(`data-evidence-${key}="([^"]*)"`))[1]);
      const field=({xpts:'mean_pts',p_win:'p_win',pts:'now',ucl:'p_ucl',top8:'p_top8'})[c.key];
      const known=block.teams.filter(t=>c.key==='pts'?Number.isFinite(t.now?.pts):c.key==='ucl'&&!X.perWorldQualification(block)?Number.isFinite(t.p_ucl??t.p_top4):Number.isFinite(t[field])).length;
      evidenceOK &&= num('eligible')===block.teams.length && num('known')===known && num('unknown')===block.teams.length-known && num('known')+num('unknown')===num('eligible')
        && markup.includes(RESULT.as_of || RESULT.fitted_through || 'unavailable');
      helps++;
    }
  }
  check(profilesOK&&pairs>0, `overview profiles: ${pairs} rows across 8 competitions ×3 profiles retain exact All-column cells/order; every visible header matches its keyed cell, with no duplicate keys`);
  check(payloadOK&&numeric>0, `overview values: ${numeric} visible numeric cells / ${visible} visible cells equal independent stored points/places/probabilities within display precision`);
  check(evidenceOK&&helps>0, `metric evidence: ${helps} non-empty disclosures reconcile known + unknown = eligible with independent field counts and the actual cutoff`);
  const old=structuredClone(RESULT.leagues[0]);
  delete old.qualification;
  old.teams.forEach(t=>{delete t.now;delete t.next5;delete t.p_uel;delete t.p_uecl;delete t.p_ucl;});
  old.uel_spots=0;old.uecl_spots=0;
  X.COLUMN_PROFILE='forecast';
  const oldColumns=X.overviewColumns(old,'league'), oldHtml=X.league(old), oldHeads=cells(oldHtml.match(/<thead>([\s\S]*?)<\/thead>/)[1],'th');
  const missing=structuredClone(old);missing.teams[0].mean_pts=null;
  const evidence=X.metricEvidenceHtml(missing,X.overviewColumns(missing,'league').find(c=>c.key==='xpts'));
  const originalResult=RESULT;X.RESULT={...RESULT,as_of:null,fitted_through:null,params:{...RESULT.params,as_of:null},worlds:null};
  const unavailable=X.metricEvidenceHtml(missing,oldColumns.find(c=>c.key==='xpts'));
  X.RESULT=originalResult;
  check(!oldColumns.some(c=>['pts','pos','pl','uel','uecl','next5'].includes(c.key)) && oldHeads.filter(c=>!c.hidden).map(c=>c.key).join(',')==='rank,team,xpts,xpos,p_win,delta,ucl,ucl_delta,rel,rel_delta'
    && evidence.includes(`data-evidence-unknown="1"`) && unavailable.includes('unavailable') && !oldHtml.includes('NaN'),
    `overview field guards: ${old.teams.length} older-shape rows omit absent groups; 1 unknown XPTS stays unknown and missing cutoff/world evidence is unavailable`);
  X.COLUMN_PROFILE=savedProfile;
}

// The four fate changes share TITLE's window and read the exact stored history values.
{
  const priorQuery=document.querySelectorAll, savedWindow=X.DWIN, savedProfile=X.COLUMN_PROFILE;
  let checked=0,missing=0,relRises=0,relFalls=0,deltaOK=true;
  const windows=X.windowsOf();
  for(const w of windows.length?windows:[null]) {
    if(w)X.DWIN=w.key;
    const dates=HISTORY.dates||[], here=RESULT.source?.date?dates.indexOf(RESULT.source.date):dates.length;
    let reference=here>0?here-1:-1;
    if(w&&here>0){reference=-1;for(let i=0;i<here;i++)if((HISTORY.meta?.[dates[i]]?.as_of||dates[i])<=w.date)reference=i;if(reference<0)reference=0;}
    const nodes=[];X.COLUMN_PROFILE='forecast';
    for(const b of RESULT.leagues) {
      const html=X.league(b);
      for(const m of html.matchAll(/<td\b([^>]*data-column="(?:ucl|uel|uecl|rel)_delta"[^>]*)>/g)) {
        const attrs=Object.fromEntries([...m[1].matchAll(/([\w-]+)="([^"]*)"/g)].map(a=>[a[1],a[2].replace(/&quot;/g,'"').replace(/&amp;/g,'&')]));
        const expectedMetric=({ucl_delta:'p_ucl',uel_delta:'p_uel',uecl_delta:'p_uecl',rel_delta:'p_releg'})[attrs['data-column']];
        deltaOK &&= attrs['data-mv-metric']===expectedMetric;
        nodes.push({expectedMetric,dataset:{mvComp:attrs['data-mv-comp'],mvTeam:attrs['data-mv-team'],mvMetric:attrs['data-mv-metric']},textContent:''});
      }
    }
    document.querySelectorAll=selector=>selector==='#view td.mv[data-mv-metric]'?nodes:[];
    X.fillMovers();
    for(const node of nodes) {
      const {mvComp:comp,mvTeam:team}=node.dataset, metric=node.expectedMetric;
      const now=RESULT.leagues.find(b=>b.competition===comp).teams.find(t=>t.team===team)[metric];
      const was=reference>=0?HISTORY.competitions?.[comp]?.[team]?.[metric]?.[reference]:null;
      if(was==null||now==null){missing++;deltaOK&&=node.textContent==='—'&&node.dataset.v==null;continue;}
      const expected=100*(now-was), rounded=Math.abs(expected)<.05?'0.0':(expected>0?'▲':'▼')+Math.abs(expected).toFixed(1);
      const good=metric==='p_releg'?expected<0:expected>0;
      deltaOK&&=Math.abs(Number(node.dataset.v)-expected)<=.000501&&node.textContent===rounded&&node.className===('mv'+(Math.abs(expected)<.05?'':good?' up':' down'));
      if(metric==='p_releg'&&Math.abs(expected)>=.05){if(expected>0)relRises++;else relFalls++;}
      checked++;
    }
  }
  // Old history cannot turn missing UEL/UECL into zero change; a true zero probability is known.
  const b=RESULT.leagues[0],t=b.teams[0],oldResult=RESULT,oldHistory=HISTORY;
  const samples=[{dataset:{mvComp:b.competition,mvTeam:t.team,mvMetric:'p_uel',v:'99'},textContent:''},{dataset:{mvComp:b.competition,mvTeam:t.team,mvMetric:'p_uecl'},textContent:''}];
  const altered=structuredClone(RESULT);altered.leagues[0].teams[0].p_uecl=0;
  X.RESULT=altered;X.HISTORY={dates:['2026-01-01',RESULT.source?.date||'2026-10-22'],meta:{'2026-01-01':{as_of:'2026-01-01'}},competitions:{[b.competition]:{[t.team]:{p_uecl:[0,0]}}}};
  document.querySelectorAll=selector=>selector==='#view td.mv[data-mv-metric]'?samples:[];X.fillMovers();
  const missingOK=samples[0].textContent==='—'&&samples[0].dataset.v==null&&samples[1].textContent==='0.0'&&Number(samples[1].dataset.v)===0;
  X.RESULT=oldResult;X.HISTORY=oldHistory;document.querySelectorAll=priorQuery;X.DWIN=savedWindow;X.COLUMN_PROFILE=savedProfile;
  if (!checked && deltaOK) console.log(`  skip    qualification deltas: no comparable earlier snapshot (${missing} unavailable cells checked as unavailable)`);
  else check(deltaOK&&checked>0,`qualification deltas: ${checked} UCL/UEL/UECL/REL cells over ${windows.length||1} shared windows equal independent snapshot comparisons (${missing} unavailable); ${relRises} REL rises are adverse, ${relFalls} falls favourable`);
  check(missingOK,'qualification delta guards: 1 absent history value stays unavailable with no stale sort value; 1 known zero remains0.0');
}

// Workspace selectors reconcile with stored evidence rather than reimplementing forecasts.
{
  X.WORKSPACE=Workspace;X.WORKSPACE_PREFS=Workspace.emptyPreferences();X.WORKSPACE_SECTION='home';
  const beforeBadge=X.BADGES, badges={Arsenal:'9825.png'};X.BADGES=badges;
  const entities=Workspace.clubEntities(RESULT,badges),sourceNames=new Set([...RESULT.leagues,...RESULT.uefa,...(RESULT.cups||[])].flatMap(b=>b.teams.map(t=>t.team)));
  const aliases=new Set(entities.flatMap(e=>e.aliases));
  const stable=Workspace.clubEntities({leagues:[{competition:'Renamed league',teams:[{team:'Arsenal FC'}]}]}, {'Arsenal FC':'9825.png'})[0];
  check(entities.length>0&&new Set(entities.map(e=>e.id)).size===entities.length&&aliases.size===sourceNames.size&&[...sourceNames].every(n=>aliases.has(n))&&stable.id==='club:fotmob:9825'&&stable.id===Workspace.clubId('Arsenal',badges),
    `workspace entities: ${entities.length} club identities cover all ${sourceNames.size} source names once; provider identity survives1 name change`);
  check(Workspace.kickoffLabel('2026-10-22T16:30:00').includes('17:30')&&Workspace.kickoffLabel('2026-12-01T16:30:00Z').includes('16:30')&&Workspace.kickoffLabel('invalid')==='Time unavailable',
    'workspace kickoff:2 audited summer/winter clock cases display UK time from source UTC instants; invalid time stays unavailable');
  check(JSON.stringify(Workspace.resolveFollowing(['club:name:Arsenal','club:fotmob:9825','club:name:unavailable'],entities))===JSON.stringify(['club:fotmob:9825','club:name:unavailable']),
    'workspace identity migration: provisional Arsenal follow resolves to provider ID and deduplicates; unavailable club remains retained');
  const ctx=Workspace.contextOf(RESULT);
  check(ctx.snapshot===RESULT.source.date&&ctx.cutoff===RESULT.as_of&&ctx.season===RESULT.params.season&&ctx.model===RESULT.model&&ctx.projectionRevision===(RESULT.source.projection_sha256??null),
    'workspace context: snapshot folder, actual data cutoff, season and model remain separate pinned fields');
  const agenda=Workspace.upcomingAgenda(RESULT,MATCHES,[],badges,20000),keys=new Set(),eligible=(MATCHES.fixtures||[]).filter(f=>!f.result&&String(f.kickoff).slice(0,10)>RESULT.as_of&&String(f.kickoff).slice(0,10)<=new Date(Date.parse(RESULT.as_of+'T00:00:00Z')+7*86400000).toISOString().slice(0,10)&&!(Number.isFinite(f.p_occurs)&&f.p_occurs<1));
  const expectedSet=new Set(eligible.map(f=>[f.competition,f.home,f.away,f.kickoff].join('|')));
  let agendaOK=agenda.length===expectedSet.size&&agenda.length>0;
  agenda.forEach((f,i)=>{const id=[f.competition,f.home,f.away,f.kickoff].join('|');agendaOK&&=expectedSet.has(id)&&!keys.has(id)&&(!i||Workspace.fixtureInstant(agenda[i-1].kickoff,agenda[i-1].competition)<=Workspace.fixtureInstant(f.kickoff,f.competition));keys.add(id);});
  const selected=Workspace.upcomingAgenda(RESULT,MATCHES,[Workspace.clubId('Arsenal',badges)],badges,1000);
  const wantedArsenal=agenda.filter(f=>f.home==='Arsenal'||f.away==='Arsenal');
  check(agendaOK&&JSON.stringify(selected)===JSON.stringify(wantedArsenal),
    `workspace agenda: ${agenda.length} exact unique confirmed source fixtures across7 days; ${selected.length} Arsenal fixtures retain club scope and kickoff order`);
  const changes=Workspace.briefingChanges(RESULT,HISTORY,X.windowsOf().find(w=>w.key==='1w')||null,[],badges);
  const home=X.homeHtml({fixtures:[]});
  check(!home.includes('YOUR FOOTBALL DESK')&&!home.includes('Next to watch')&&!home.includes('What changed')&&!home.includes('home-follow')&&!home.includes('viewing-plan')&&home.includes('home-previous')&&home.includes('home-next'),'Home replacement:0 retired briefing/follow/plan sections;2 date arrows and explicit empty day');
  check(changes.rows.every(r=>{const source=[...RESULT.leagues,...RESULT.uefa,...(RESULT.cups||[])].find(b=>b.competition===r.competition).teams.find(t=>t.team===r.team),before=HISTORY.competitions[r.competition][r.team][r.metric][changes.index];return r.now===source[r.metric]&&r.before===before&&Math.abs(r.delta-100*(r.now-before))<1e-10;}),`Retained change selector:${changes.rows.length} source identities remain exact outside retired Home briefing`);
  const bad=structuredClone(RESULT);bad.leagues[0].teams[0].p_win=1.3;
  const issues=Workspace.snapshotIssues(bad),badChanges=Workspace.briefingChanges(bad,HISTORY,X.windowsOf().find(w=>w.key==='1w')||null);
  const noHistory=Workspace.briefingChanges(RESULT,{dates:[RESULT.source.date]},null);
  const injected=issues.find(i=>i.competition===bad.leagues[0].competition&&i.team===bad.leagues[0].teams[0].team&&i.metric==='p_win');
  const existingIssues=Workspace.snapshotIssues(RESULT).filter(i=>!(i.competition===bad.leagues[0].competition&&i.team===bad.leagues[0].teams[0].team&&i.metric==='p_win'));
  check(issues.length===existingIssues.length+1&&injected?.value===1.3&&bad.leagues[0].teams[0].p_win===1.3&&!badChanges.rows.some(r=>r.team===bad.leagues[0].teams[0].team&&r.metric==='p_win')&&noHistory.index===-1&&noHistory.rows.length===0,
    `workspace evidence guards: 1 injected invalid probability remains raw/reported beside ${existingIssues.length} existing issues and is omitted from briefing; 1-snapshot history invents0 updates`);
  const state={version:1,following:['club:fotmob:9825'],landing:'home',savedViews:[{id:'one',name:'Title race',hash:'#section=races&tab=English+Premier+League&date=2026-08-22&dw=1m&cols=forecast'}]};
  let stored='',blocked=false;const storage={getItem:()=>stored,setItem:(k,v)=>{stored=v;}};
  const persist=Workspace.persistPreferences(storage,state),loaded=Workspace.loadPreferences(storage),imported=Workspace.importPreferences(JSON.stringify(state));
  const rejects=[{...state,version:99},{...state,savedViews:[{...state.savedViews[0],hash:'#section=races&tab=English+Premier+League'}]},{...state,savedViews:[{...state.savedViews[0],hash:'javascript:alert(1)'}]}];let rejected=0;
  for(const value of rejects){try{Workspace.importPreferences(JSON.stringify(value));}catch{rejected++;}}
  check(persist&&JSON.stringify(loaded)===JSON.stringify(imported)&&loaded.savedViews[0].hash.includes('date=2026-08-22')&&rejected===3&&!Workspace.persistPreferences({setItem(){throw Error('blocked');}},state)&&Workspace.loadPreferences({getItem(){throw Error('blocked');}}).following.length===0,
    'workspace preferences:1 export/import/storage round-trip preserves followed IDs and pinned context;3 invalid/version/unpinned imports reject; blocked storage stays usable');
  const legacy=[['#tab=English+Premier+League&view=points','races'],['#tab=Track+record','explore'],['#tab=UEFA+Champions+League&view=paths','races'],['#tab=Ratings','explore']];
  check(legacy.every(([h,s])=>Workspace.sectionFromRoute(h)===s)&&Workspace.sectionFromRoute('')==='home'&&Workspace.sectionFromRoute('#section=clubs&tab=English+Premier+League')==='clubs',
    'workspace routes:4 legacy competition/research links retain destination; empty route starts Home; explicit section wins');
  const originalLocation=globalThis.location,originalHistory=globalThis.history,savedTab=X.TAB;
  globalThis.location={hash:''};globalThis.history={pushState(_a,_b,h){location.hash=h;},replaceState(_a,_b,h){location.hash=h;}};
  X.TAB=RESULT.leagues[0].competition;X.WORKSPACE_SECTION='races';X.DWIN='1m';X.writeHash(false);
  const h=new URLSearchParams(location.hash.slice(1));
  check(h.get('section')==='races'&&h.get('date')===RESULT.source.date&&h.get('dw')==='1m'&&h.get('tab')===RESULT.leagues[0].competition,
    'workspace route identity: section, exact snapshot folder, competition and shared1M window serialize together');
  globalThis.location=originalLocation;globalThis.history=originalHistory;X.TAB=savedTab;X.DWIN='1w';X.WORKSPACE=null;X.BADGES=beforeBadge;
}

// Entity index, search and inspector evidence use independent source populations.
{
  const decode=value=>value.replace(/&quot;/g,'"').replace(/&lt;/g,'<').replace(/&amp;/g,'&');
  X.WORKSPACE=Workspace;X.WORKSPACE_PREFS=Workspace.emptyPreferences();
  X.RESULT=RESULT;X.PLAYERS=PLAYERS;X.PLAYERS_FOR=RESULT;X.PLAYERS_STATUS=PLAYERS?'ready':'missing';
  const entities=Workspace.playerEntities(RESULT,PLAYERS),sourceRows=Object.entries(PLAYERS?.competitions||{}).flatMap(([comp,b])=>(b.players||[]).map(row=>({comp,row})));
  if(sourceRows.length) {
    const ids=new Set(sourceRows.map(({row})=>'player:fotmob:'+row.id)),seen=new Set();let sourceOK=entities.length===ids.size,rows=0;
    for(const e of entities)for(const r of e.rows){rows++;const key=r.competition+'|'+e.id;sourceOK&&=!seen.has(key)&&sourceRows.some(s=>s.comp===r.competition&&'player:fotmob:'+s.row.id===e.id&&JSON.stringify(s.row)===JSON.stringify(r.source));seen.add(key);}
    check(sourceOK&&rows===sourceRows.length&&rows>0,`workspace player entities: ${entities.length} provider identities preserve ${rows} independent competition rows without merging totals`);
    const wrong=structuredClone(PLAYERS);wrong.as_of='1900-01-01';
    const sample=[{type:'player',id:'player:fotmob:1',name:'Alex García',aliases:['Alex Garcia'],teams:['Alpha']},{type:'player',id:'player:fotmob:2',name:'Alex García',teams:['Beta']},{type:'player',id:'player:fotmob:3',name:'Aaron Wan-Bissaka'},{type:'player',id:'player:fotmob:4',name:'Bukayo Saka'}];
    const search=Workspace.searchEntities(sample,'alex garcia');
    check(search.length===2&&new Set(search.map(e=>e.id)).size===2&&Workspace.searchEntities(sample,'Saka')[0]?.id==='player:fotmob:4'&&Workspace.searchEntities(sample,'Alex Beta')[0]?.id==='player:fotmob:2'&&Workspace.playerEntities(RESULT,wrong).length===0,
      'workspace entity search guards:2 same-name players retain distinct IDs, accents normalize, word match precedes substring, club qualifier narrows identity; wrong-cutoff payload yields0 players');
    const target=entities.find(e=>e.rows.length>1&&e.teams.includes('Arsenal'))||entities[0],race=Workspace.raceEntities(RESULT).find(e=>e.metric==='p_releg');
    const followed=[target.id,...(race?[race.id]:[])],selected=Workspace.upcomingAgenda(RESULT,MATCHES,followed,{},20000,PLAYERS);
    const all=Workspace.upcomingAgenda(RESULT,MATCHES,[],{},20000),wanted=all.filter(f=>target.teams.includes(f.home)||target.teams.includes(f.away)||race?.competition===f.competition);
    check(all.length>0&&JSON.stringify(selected)===JSON.stringify(wanted)&&Workspace.upcomingAgenda(RESULT,MATCHES,['player:fotmob:unavailable'],{},20000,PLAYERS).length===0,
      `workspace following scope: ${selected.length} player/race fixtures equal source club-or-competition union;1 unavailable player does not widen to all ${all.length} fixtures`);
    const chosen=[...new Set([target.id,...entities.slice(0,3).map(e=>e.id),...entities.filter(e=>e.rows.some(r=>Object.keys(r.source.by_team||{}).length>1)).slice(0,2).map(e=>e.id)])];let cells=0,off=[];
    for(const id of chosen) {
      const e=entities.find(e=>e.id===id),html=X.playerCardHtml(id),shown=[...html.matchAll(/data-player-evidence="([^"]+)" data-value="([^"]*)"/g)];
      let expected=0;
      for(const r of e.rows)for(const [club,source] of [['',r.source],...(Object.keys(r.source.by_team||{}).length>1?Object.entries(r.source.by_team):[])])for(const metric of ['matches','minutes','goals','xg','assists','shots']) {
        expected++;cells++;const key=[id,r.competition,club,metric].join('|'),entry=shown.find(m=>decode(m[1])===key),want=Number.isFinite(source[metric])?source[metric]:null;
        if(!entry||(entry[2]===''?null:Number(entry[2]))!==want)off.push(key);
      }
      if(shown.length!==expected)off.push(id+' row count');
    }
    check(cells>0&&!off.length,`workspace player inspector: ${cells} rendered source values across ${chosen.length} identities equal competition/club contributions, with unknowns retained`,off.slice(0,4).join('; '));
    const copied=structuredClone(PLAYERS),comp=Object.keys(copied.competitions)[0],p=copied.competitions[comp].players[0];p.xg=null;
    X.PLAYERS=copied;const html=X.playerCardHtml('player:fotmob:'+p.id),key=['player:fotmob:'+p.id,comp,'','xg'].join('|');
    check(html.includes(`data-player-evidence="${key.replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/</g,'&lt;')}" data-value=""><dt>xG</dt><dd>—</dd>`),'workspace player inspector guard:1 injected unknown xG renders unavailable, never zero');
    X.PLAYERS=PLAYERS;
    const state={...Workspace.emptyPreferences(),following:followed,followLabels:{[target.id]:target.name}},round=Workspace.importPreferences(JSON.stringify(state));
    let rejected=false;try{Workspace.importPreferences(JSON.stringify({...state,following:['javascript:bad']}));}catch{rejected=true;}
    check(JSON.stringify(round.following)===JSON.stringify(followed)&&round.followLabels[target.id]===target.name&&rejected,`workspace typed preferences: ${followed.length} player/race follows and saved label round-trip;1 unsupported identity rejects`);
  } else console.log('  skip    workspace player identity/card numeric checks (snapshot has0 player evidence rows)');
  const matches=Workspace.matchEntities(RESULT,MATCHES,GWD),unique=new Set(matches.map(e=>e.id));
  const source=[...(MATCHES?.fixtures||[]),...Object.entries(GWD?.leagues||{}).flatMap(([competition,g])=>(g.fixtures||[]).map(f=>({...f,competition}))),...Object.entries(GWD?.phases||{}).flatMap(([competition,g])=>(g.fixtures||[]).map(f=>({...f,competition})))];
  const wanted=new Set(source.filter(f=>f.home&&f.away&&f.competition&&/^\d{4}-\d{2}-\d{2}/.test(f.kickoff||'')&&!(Number.isFinite(f.p_occurs)&&f.p_occurs<1)&&!(f.result&&f.kickoff.slice(0,10)>RESULT.as_of)).map(f=>'match:'+encodeURIComponent(f.competition)+'|'+[f.home,f.away,f.kickoff.slice(0,10)].join('|')));
  check(matches.length>0&&unique.size===matches.length&&wanted.size===unique.size&&[...wanted].every(id=>unique.has(id)),`workspace match search: ${matches.length} unique confirmed fixture identities equal source union, keeping competition separate`);
  const artificial={home:'Alpha',away:'Beta',kickoff:RESULT.as_of+' 12:00:00',competition:'Cup A'};
  const future={...artificial,kickoff:'2099-01-01 12:00:00',result:[2,1]};
  const isolated=Workspace.matchEntities(RESULT,{fixtures:[artificial,{...artificial,competition:'Cup B'},future,{...artificial,p_occurs:.5,competition:'Conditional'}]},null);
  check(isolated.length===2&&new Set(isolated.map(e=>e.competition)).size===2,'workspace match search guards:2 identical pair/day fixtures retain competition identity;1 future completed result and1 conditional pairing excluded');
  const races=Workspace.raceEntities(RESULT),leagues=RESULT.leagues||[],r=races.find(e=>e.metric==='p_releg'),w=X.windowsOf().find(w=>w.key==='1w')||null;
  const changes=r?Workspace.briefingChanges(RESULT,HISTORY,w,[r.id]):{rows:[],index:-1};
  check(races.length>0&&new Set(races.map(e=>e.id)).size===races.length&&races.every(e=>e.season===RESULT.params.season)&&changes.rows.every(row=>row.competition===r.competition&&row.metric==='p_releg'),
    `workspace race identities: ${races.length} season/competition/fate IDs remain unique; ${changes.rows.length} followed-race updates stay in their own population`);
  const clockEntries=X.matchFixtures().filter(e=>e.f.ladder&&!e.f.result).slice(0,2);
  check(clockEntries.length===2&&clockEntries.every(e=>X.matchCardHtml(e).includes(Workspace.kickoffLabel(e.f.kickoff,e.competition))),
    'workspace kickoff consistency:2 actual match-card headers use the same competition-local instant/UK formatter as Home and search');
  const previousLocation=globalThis.location,previousHistory=globalThis.history,previousFocus=X.FOCUS,previousPage=X.TEAM_PAGE,previousPlayer=X.PLAYER_FOCUS;
  globalThis.location={hash:'#section=races&tab=English+Premier+League&team=Arsenal&page=1&player=player%3Afotmob%3A961995&date='+RESULT.source.date};
  globalThis.history={pushState(_a,_b,h){location.hash=h;},replaceState(_a,_b,h){location.hash=h;}};
  X.applyHash();X.writeHash(false);const nested=new URLSearchParams(location.hash.slice(1));
  check(X.TEAM_PAGE&&X.FOCUS==='Arsenal'&&X.PLAYER_FOCUS==='player:fotmob:961995'&&nested.get('team')==='Arsenal'&&nested.get('page')==='1'&&nested.get('player')===X.PLAYER_FOCUS,
    'workspace inspector route:1 player on a full club page preserves parent team/page plus exact player identity through parse/serialize');
  X.FOCUS=previousFocus;X.TEAM_PAGE=previousPage;X.PLAYER_FOCUS=previousPlayer;globalThis.location=previousLocation;globalThis.history=previousHistory;
  X.WORKSPACE=null;
}

// Match Centre uses actual cache-normalized fixtures, plus adversarial pure selector cases.
if(centrePath&&centrePath!=='-'){
 const evidence=JSON.parse(readFileSync(centrePath,'utf8')),agenda=evidence.agenda,centres=evidence.centres;
 X.WORKSPACE=Workspace;X.WORKSPACE_PREFS=Workspace.emptyPreferences();X.MC=MatchCentre;
 const rows=MatchCentre.agendaRows(RESULT,agenda,PLAYERS,{},[],{period:'season'});
 const ids=new Set(rows.map(f=>f.id));
 check(rows.length>0&&ids.size===rows.length&&rows.every((f,i)=>!f.result&&f.kickoff.slice(0,10)>RESULT.as_of&&(!i||Workspace.fixtureInstant(f.kickoff,f.competition)>=Workspace.fixtureInstant(rows[i-1].kickoff,rows[i-1].competition))),`Match Centre agenda: ${rows.length} unique future fixtures in chronological order`);
 const html=X.workspaceAgendaHtml(agenda),rendered=[...html.matchAll(/data-agenda-fixture="([^"]+)"/g)];
 check(rendered.length>0&&new Set(rendered.map(m=>m[1])).size===rendered.length,`Match Centre agenda HTML: ${rendered.length} distinct fixture rows`);
 const none=MatchCentre.agendaRows(RESULT,agenda,PLAYERS,{},[],{scope:'following'}),unknown=MatchCentre.agendaRows(RESULT,agenda,PLAYERS,{},['club:unknown'],{scope:'following'});
 check(none.length===0&&unknown.length===0,'Match Centre following:2 empty/unknown scopes stay empty');
 check(MatchCentre.ukDay('2026-08-22 23:30:00')==='2026-08-23'&&MatchCentre.ukDay('2026-10-25 23:30:00')==='2026-10-25','Match Centre date:2 UK summer/winter midnight identities');
 check(Workspace.fixtureInstant('2026-10-20 21:00:00','UEFA Champions League')===Date.parse('2026-10-20T19:00:00Z')&&Workspace.kickoffLabel('2026-10-20 21:00:00','UEFA Champions League').includes('20:00')&&Workspace.kickoffLabel('2026-10-27 21:00:00','UEFA Champions League').includes('20:00')&&Workspace.kickoffLabel('2026-10-20 20:00:00','English Premier League').includes('20:00'),'Fixture clocks:4 competition-local/UTC/UK identities include PSG–Barcelona and both sides of autumn clock change');
 const directionCases=[{side:'home',x:98,y:22},{side:'away',x:98,y:22},{side:'home',x:7.8,y:41,own_goal:true},{side:'away',x:7.8,y:41,own_goal:true}];
 check(directionCases.every(s=>{const p=MatchCentre.shotPosition(s);return p.x===(s.side==='home'?s.x:105-s.x)&&p.y===(s.side==='home'?68-s.y:s.y);}), 'Match Centre direction:4 asymmetric regular/own-goal home/away cases preserve source goal-relative side');
 let shots=0,events=0,players=0,curves=0,odds=0,forms=0;
 for(const d of centres){
  const p=X.centrePreviewHtml(d);
  if(d.pre_match){
   const values=[...p.matchAll(/data-centre-odds="([^"]+)"/g)].map(m=>+m[1]),f=d.pre_match.fixture;
   check(values.length===3&&Math.abs(values.reduce((a,b)=>a+b,0)-1)<.00002&&values[0]===f.ladder.h1&&values[2]===f.ladder.a1,`Match Centre preview ${d.fixture.id}:3 home/draw/away probabilities reconcile`);odds+=3;
   check(d.pre_match.as_of<d.fixture.kickoff.slice(0,10),`Match Centre preview ${d.fixture.id}:1 cutoff precedes match day`);
   for(const c of Object.values(d.pre_match.context||{}))for(const row of c.form){forms++;check(row.kickoff.slice(0,10)<=d.pre_match.as_of,`Match Centre form ${d.fixture.id}:1 result through pre-match cutoff`);}
  }
  if(!d.facts){check(!MatchCentre.headerHtml(d,'preview').includes('Shots: covered'),`Match Centre preview ${d.fixture.id}: no future shot coverage`);continue;}
  const f=d.facts,frames=MatchCentre.replayFrames(f),last=MatchCentre.atFrame(f,Infinity),start=MatchCentre.atFrame(f,0);
  const pitch=MatchCentre.pitchHtml(d,Infinity,['red','blue']),shotIds=[...pitch.matchAll(/data-shot="([^"]+)"/g)].map(m=>m[1]);
  check(shotIds.length===f.shots.filter(s=>s.x!=null&&s.y!=null).length&&shotIds.every(id=>f.shots.some(s=>s.id===id)),`Match Centre pitch ${d.fixture.id}:${shotIds.length} exact located shot IDs`);shots+=shotIds.length;
  const plotted=[...pitch.matchAll(/data-pitch-x="([^"]+)" data-pitch-y="([^"]+)" data-shot-side="([^"]+)" data-replay-order="[^"]+" data-shot="([^"]+)"/g)];
  const coordinatesOK=marks=>marks.length===shotIds.length&&marks.every(m=>{const shot=f.shots.find(s=>s.id===m[4]);return shot&&Math.abs(+m[1]-(shot.side==='away'?105-shot.x:shot.x))<1e-9&&Math.abs(+m[2]-(shot.side==='away'?shot.y:68-shot.y))<1e-9;});
  check(plotted.length>0&&coordinatesOK(plotted),`Match Centre orientation ${d.fixture.id}:${plotted.length} located shots preserve source y-axis conversion and opposing attacks`);
  const broken=plotted.map(m=>[...m]);broken[0][2]=String(+broken[0][2]+1);
  check(!coordinatesOK(broken),`Match Centre orientation ${d.fixture.id}:1 deliberate wrong-y marker rejected`);
  const timeline=MatchCentre.timelineHtml(d,frames.length-1,['red','blue']);
  check(timeline.indexOf('data-match-replay=')<timeline.indexOf('id="centre-players"')&&timeline.includes('Full-match stats')&&!MatchCentre.SECTIONS.some(([id])=>id==='players'),`Match Centre layout ${d.fixture.id}:${f.players.length} players below Timeline;4 sections`);
  const header=MatchCentre.headerHtml({...d,facts:{...f,provider_kickoff:'2026-10-21T20:00:00Z'}},'timeline');
  check(header.includes(Workspace.kickoffLabel(d.fixture.kickoff,d.fixture.competition))&&!header.includes('London')&&!header.includes('Kickoff differs'),`Match Centre header ${d.fixture.id}:1 UK-time kickoff without source-disagreement banner`);
  const replay=MatchCentre.replayHtml(d,frames.length-1,['red','blue']),eventIds=[...replay.matchAll(/data-event="([^"]+)"/g)].map(m=>m[1]);
  check(eventIds.length===f.events.length&&eventIds.every(id=>f.events.some(e=>e.id===id))&&start.shots.length===0&&start.events.length===0&&last.goals.every((v,i)=>v===d.fixture.result[i]),`Match Centre replay ${d.fixture.id}:${eventIds.length} exact events; empty start and reconciled final score`);events+=eventIds.length;
  const curve=MatchCentre.curveData(d);
  for(const [i,side] of ['home','away'].entries()){
   const expected=f.shots.filter(s=>s.side===side&&!s.own_goal&&s.xg!=null).reduce((sum,s)=>sum+s.xg,0),values=curve.vals.get(d.fixture[side]);
   check(values.length===frames.length&&values[0]===0&&Math.abs(values.at(-1)-expected)<1e-10&&values.every((v,k)=>!k||v>=values[k-1]),`Match Centre xG ${d.fixture.id}/${side}:${values.length} cumulative frames reconcile with eligible shots`);curves++;
  }
  const ph=MatchCentre.playersHtml(d),pv=[...ph.matchAll(/data-match-player-stat="([^"]+)" data-value="([^"]*)"/g)];
  check(pv.length===6*f.players.length&&pv.every(m=>m[2]===''||Number.isFinite(+m[2])),`Match Centre players ${d.fixture.id}:${pv.length} typed metric cells; unavailable stays blank`);players+=f.players.length;
  const playerRows=[...ph.matchAll(/<tr data-match-player="([^"]*)">([\s\S]*?)<\/tr>/g)];
  const valuesOK=rows=>rows.length===f.players.length&&rows.every(m=>{const p=f.players.find(p=>Workspace.esc(p.id)===m[1]),cells=[...m[2].matchAll(/data-match-player-stat="([^"]+)" data-value="([^"]*)"/g)];return p&&cells.length===6&&cells.every(c=>(c[2]===''?null:+c[2])===(p[c[1]]??null));});
  check(valuesOK(playerRows)&&ph.includes('<th>MIN</th><th>Goals</th><th>xG</th><th>Assists</th><th>xA</th><th>Shots</th>'),`Match player columns:${playerRows.length} rows preserve six exact metrics in requested order`);
  const brokenPlayers=playerRows.map(m=>[...m]);brokenPlayers[0][2]=brokenPlayers[0][2].replace(/(data-match-player-stat="xa" data-value=")[^"]*"/,'$1999"');
  check(!valuesOK(brokenPlayers),'Match xA fault:1 shifted value rejected');
  const assists=f.events.filter(e=>e.type==='Goal'&&!e.own_goal&&e.assist?.name&&f.shots.some(s=>s.id===e.shot_id&&s.goal&&!s.own_goal&&s.side===e.side&&s.x!=null&&s.y!=null));
  check(assists.every(e=>{const mark=pitch.match(new RegExp('data-shot="'+e.shot_id+'"[\\s\\S]*?</g>'))?.[0];return mark?.includes('Assist · '+Workspace.esc(Workspace.esc(e.assist.name)));}),`Pitch assists:${assists.length} explicitly linked goal-shot tooltips preserve named assist`);
  const codedCurve=MatchCentre.curveData(d,{code:Workspace.teamCode});
  check(codedCurve.goals.every(g=>g.tip.includes(g.text.replaceAll('–','-')+' · '+Workspace.teamCode(d.fixture.home)+'-'+Workspace.teamCode(d.fixture.away)))&&!codedCurve.goals.some(g=>g.tip.includes('home–away')),`Goal tooltips:${codedCurve.goals.length} exact running scores with home-away display codes`);
  const chance=X.centreChancesHtml(d);
  check(chance.includes('id="lcmatch"')&&!chance.includes('stroke="undefined"')&&chance.includes('data-chart-highlights')&&X.LC.lcmatch.what==='a match minute',`Match Centre chances ${d.fixture.id}:shared line primitive,valid colours and native highlights`);
  const goalMarks=[...chance.matchAll(/data-line-event="([^"]+)" data-line-team="([^"]+)" data-line-index="([^"]+)" data-line-value="([^"]+)" data-line-score="([^"]+)"/g)],expectedGoals=f.events.filter(e=>e.type==='Goal'&&e.side);
  const goalMarksOK=marks=>marks.length===expectedGoals.length&&marks.every(m=>{const event=expectedGoals.find(e=>e.id===m[1]),index=curve.frames.findIndex(frame=>frame.order===event?.order),team=event&&d.fixture[event.side];return event&&m[2]===Workspace.esc(team)&&+m[3]===index&&+m[4]===curve.vals.get(team)[index]&&m[5]===MatchCentre.atFrame(f,event.order).goals.join('–');});
  check(goalMarksOK(goalMarks),`Match Centre goal overlay ${d.fixture.id}:${goalMarks.length} running scores at exact goal frames on benefiting team xG lines`);
  if(goalMarks.length){const brokenGoals=goalMarks.map(m=>[...m]);brokenGoals[0][4]=String(+brokenGoals[0][4]+1);check(!goalMarksOK(brokenGoals),`Match Centre goal overlay ${d.fixture.id}:1 shifted goal marker rejected`);}
  const bridge=X.centreImpactHtml(d),b=[...bridge.matchAll(/data-bridge-before="([^"]+)"/g)].map(m=>+m[1]);
  check(b.length===(d.forecast_change?.rows||[]).length&&b.every((v,i)=>v===d.forecast_change.rows[i].before),`Match Centre impact ${d.fixture.id}:${b.length} observed forecast values retain source`);
 }
 check(shots>0&&events>0&&players>0&&curves>0&&odds>0&&forms>0,`Match Centre coverage:${shots} shots,${events} events,${players} players,${curves} curves,${odds} odds,${forms} form results`);
 const synthetic={season:2026,mode:'played',fixture:{home:'Alpha',away:'Beta',competition:'League',kickoff:'2026-10-21 15:00:00',result:[2,1],outcome:'fulltime'},pre_match:{payload:12,fixture:{n:100,score_cap:3,score_counts:[[5,10,5,0],[20,15,10,0],[0,30,5,0],[0,0,0,0]],ladder:{h1:.5,h2:0,h3:0,d:.25,a1:.25,a2:.05,a3:0}}}};
 let r=MatchCentre.realisedForecast(synthetic);
 check(r.exact===.3&&r.count===30&&r.outcome.value===.5&&r.margin.value===.5&&r.margin.label==='Alpha by 1','Realised forecast:3 probabilities equal exact100-world score/result/margin counts');
 const away=structuredClone(synthetic);away.fixture.result=[1,2];r=MatchCentre.realisedForecast(away);
 check(r.exact===.1&&r.outcome.value===.25&&r.margin.value===.2&&r.index===2,'Realised forecast:away2–1 uses3 home-oriented sources correctly');
 const draw=structuredClone(synthetic);draw.fixture.result=[1,1];r=MatchCentre.realisedForecast(draw);
 check(r.exact===.15&&r.outcome.value===.25&&r.margin.value===.25&&r.index===1,'Realised forecast:draw score/result/level margin reconcile to diagonal');
 const historical=structuredClone(synthetic);delete historical.pre_match.fixture.score_counts;historical.pre_match.payload=11;historical.pre_match.fixture.top=[['2-0',.31],['1-0',.2]];r=MatchCentre.realisedForecast(historical);
 check(r.exact===null&&r.bound===.2&&MatchCentre.realisedHtml(historical).includes('Score not retained'),'Realised forecast:1 unretained historical score is unavailable, with a valid bound');
 historical.pre_match.fixture.top.push(['2-1',.17]);r=MatchCentre.realisedForecast(historical);
 check(r.exact===.17&&r.exact_source==='retained-score','Realised forecast:1 retained historical exact score uses its original probability');
 const aet=structuredClone(synthetic);aet.fixture.outcome='afterextratime';aet.fixture.result=[0,1];aet.facts={coverage:{timeline:true,goals_reconcile:true},events:[{type:'Goal',side:'away',period:'FirstHalfExtra'}]};r=MatchCentre.realisedForecast(aet);
 check(r.score.join('-')==='0-0'&&r.exact===.05&&r.outcome.value===.25,'Realised forecast:1 AET goal excluded; actual90-minute draw and0–0 probability recovered');
 aet.facts.coverage.goals_reconcile=false;check(MatchCentre.realisedForecast(aet).score===null,'Realised forecast:1 unreconciled AET timeline cannot fabricate a90-minute score');
 const overflow=structuredClone(synthetic);overflow.fixture.result=[4,0];r=MatchCentre.realisedForecast(overflow);
 check(r.exact===null&&r.exact_source==='overflow'&&r.margin.label==='Alpha by 3+','Realised forecast:1 capped score stays unavailable;3+ goal margin explicitly grouped');
 const malformed=structuredClone(synthetic);malformed.pre_match.fixture.score_counts[0][0]++;
 check(MatchCentre.realisedForecast(malformed).exact===null,'Realised forecast:1 deliberate extra world rejects an invalid full score grid');
 const displayed=MatchCentre.realisedHtml(synthetic),cells=[...displayed.matchAll(/data-realised-prob="([^"]+)" data-value="([^"]*)"/g)].map(m=>+m[2]);
 check(cells.length===3&&cells[0]===.3&&cells[1]===.5&&cells[2]===.5,'Realised forecast HTML:3 displayed probability cells reconcile to independent score counts');
 const missing=structuredClone(centres.find(d=>d.facts));missing.facts.shots=[];missing.facts.coverage.shotmap=false;
 const missingHtml=MatchCentre.replayHtml(missing,1,['red','blue']);
 check(missingHtml.includes('shot xG unavailable')&&missingHtml.includes('no retained shot map')&&!missingHtml.includes('known shot xG 0.00–0.00'),'Match Centre missing map:1 nonempty event fixture shows unavailable xG/positions');
 const planRows=[{id:'a',kickoff:'2026-10-22 14:00:00'},{id:'b',kickoff:'2026-10-22 15:59:00'},{id:'c',kickoff:'2026-10-22 18:00:00'}],plan=MatchCentre.viewingPlan(planRows,new Set(['a','b','c']));
 check(plan.length===3&&plan[0].clash&&plan[1].clash&&!plan[2].clash,'Match Centre viewing plan:3 fixtures;119-minute clash and121-minute separation');
 X.WORKSPACE=null;
} else console.log('  skip    Match Centre cache/render evidence (no evidence fixture supplied)');

// Club command centre: independent fixture/player source accounting plus adversarial scales.
if(centrePath&&centrePath!=='-'){
 const agenda=JSON.parse(readFileSync(centrePath,'utf8')).agenda,pool=Workspace.clubFixturePool(RESULT,GWD,agenda,MATCHES.fixtures);
 X.WORKSPACE=Workspace;X.MC=MatchCentre;X.WORKSPACE_PREFS=Workspace.emptyPreferences();X.AGENDA_CACHE.set(RESULT.source.projection_sha256,agenda);
 const fixtureRows=pool.fixtures.map(f=>({f,html:Workspace.fixtureHtml(f,f.competition)}));
 const fixtureOK=(html,f)=>{const home=/data-fixture-home="([^"]*)"/.exec(html)?.[1],away=/data-fixture-away="([^"]*)"/.exec(html)?.[1],score=/data-fixture-score="([^"]*)"/.exec(html)?.[1];return home===Workspace.esc(f.home)&&away===Workspace.esc(f.away)&&score===(f.result?f.result.map(Number).join('-'):'')&&html.indexOf('class="fixture-main"')<html.indexOf('class="fixture-meta"')&&!html.includes('(UK time)');};
 check(fixtureRows.length>0&&fixtureRows.every(({html,f})=>fixtureOK(html,f)),`Lean fixtures:${fixtureRows.length} source home/away/result identities; primary match before secondary metadata; no repeated timezone suffix`);
 const example=fixtureRows.find(r=>r.f.result),damaged=example.html.replace(/data-fixture-score="[^"]*"/,'data-fixture-score="999-999"');
 check(!fixtureOK(damaged,example.f),'Lean fixture fault:1 deliberately wrong displayed result rejected');
 const names=['Arsenal','Chelsea','Real Madrid','Waldhof Mannheim'],primary=RESULT.leagues[0].competition;
 const truth=clubSourcePath&&clubSourcePath!=='-'?JSON.parse(readFileSync(clubSourcePath,'utf8')):null;
 let scalarCount=0,scalarOff=[],matchesChecked=0;
 for(const b of [...RESULT.leagues,...RESULT.uefa])for(const row of b.teams){
  const p=Workspace.clubPerformance(RESULT,pool,row.team,{competition:b.competition});
  for(const key of ['pl','gf','ga']){scalarCount++;if(p[key]!==row.real?.[key])scalarOff.push(row.team+'/'+key);}
  if(p.w+p.d+p.l!==p.pl)scalarOff.push(row.team+'/WDL');
 }
 check(scalarCount>0&&!scalarOff.length,`Club source parity:${scalarCount} PL/GF/GA values and every W+D+L identity equal competition sources`,scalarOff.slice(0,5).join(';'));
 if(truth){
  const expected=new Set(truth.map(Workspace.clubFixtureId)),actual=new Set(pool.fixtures.filter(f=>f.result).map(Workspace.clubFixtureId));
  check(expected.size>0&&expected.size===actual.size&&[...expected].every(k=>actual.has(k)),`Club match coverage:${expected.size} exact played fixture IDs equal the cutoff-filtered master CSV`);
  for(const team of [...new Set(truth.flatMap(f=>[f.home,f.away]))]){
   const source=truth.filter(f=>f.home===team||f.away===team),p=Workspace.clubPerformance(RESULT,pool,team);
   const gf=source.reduce((a,f)=>a+f.result[f.home===team?0:1],0),ga=source.reduce((a,f)=>a+f.result[f.home===team?1:0],0);matchesChecked+=source.length;
   if(p.pl!==source.length||p.gf!==gf||p.ga!==ga)scalarOff.push(team+'/all-competition source sum');
  }
  check(matchesChecked>0&&!scalarOff.length,`Club all-competition totals:${matchesChecked} side-appearances equal independent master match sums`,scalarOff.slice(0,5).join(';'));
 }else console.log('  skip    Club master CSV equality (no independent source fixture supplied)');
 let renderedCells=0,playerCells=0,forecastCells=0,summaryCells=0;
 X.CLUB_SCOPE='all';X.CLUB_VENUE='all';X.CLUB_PERIOD='season';X.CLUB_COMPARE=['Arsenal','Chelsea'];X.CLUB_COMPARE_SCOPE=primary;
 for(const team of names){
  X.CLUB_SCOPE='all';const html=X.clubMetricTableHtml([team],pool),p=Workspace.clubPerformance(RESULT,pool,team),r=Workspace.clubStrength(RESULT,team);
  const expected={pl:p.pl,w:p.w,d:p.d,l:p.l,gf:p.pl?p.gf:null,ga:p.pl?p.ga:null,gd:p.pl?p.gd:null,xg:p.xg,xga:p.xga,xgf_rate:p.xgf_rate,xga_rate:p.xga_rate,elo:r.elo??null,att:r.att??null,def:r.def??null,net:r.net??null};
  const cells=[...html.matchAll(/data-club-metric="([^"]+)" data-value="([^"]*)"/g)];
  for(const m of cells){renderedCells++;const key=m[1].split('|').at(-1),v=m[2]===''?null:+m[2];if(v!==expected[key])scalarOff.push(team+'/render/'+key);}
  X.CLUB_SECTION='squad';const squad=X.clubSquadHtml(team),source=Workspace.clubPlayerContributions(RESULT,PLAYERS,team);
  for(const m of squad.matchAll(/data-club-player="([^"]+)" data-value="([^"]*)"/g)){const [id,key]=m[1].split('|'),player=source.rows.find(p=>p.id===id);playerCells++;if((m[2]===''?null:+m[2])!==player[key])scalarOff.push(team+'/player/'+id+'/'+key);}
  X.CLUB_SECTION='season';const season=X.clubSeasonHtml(team,pool);
  for(const m of season.matchAll(/data-club-fate="([^"]+)" data-value="([^"]*)"/g)){const [competition,key]=m[1].split('|'),row=[...RESULT.leagues,...RESULT.uefa,...RESULT.cups].find(b=>b.competition===competition).teams.find(t=>t.team===team);forecastCells++;if(+m[2]!==row[key])scalarOff.push(team+'/fate/'+key);}
  for(const m of season.matchAll(/data-club-summary="([^"]+)" data-value="([^"]*)"/g)){summaryCells++;const [competition,key]=m[1].split('|'),b=[...RESULT.leagues,...RESULT.uefa,...RESULT.cups].find(b=>b.competition===competition),row=b.teams.find(t=>t.team===team),expected={PL:row.now?.pl??row.real?.pl,POS:X.placesNow(b)?.[team],PTS:row.now?.pts??row.real?.pts,XPTS:row.mean_pts,XPOS:row.mean_pos};if((m[2]===''?null:+m[2])!==(expected[key]??null))scalarOff.push(team+'/summary/'+key);}
  const schedule=X.clubScheduleHtml(team,pool),scheduleIds=[...schedule.matchAll(/data-club-schedule="([^"]+)"/g)].map(m=>m[1]);
  check(scheduleIds.length===pool.fixtures.filter(f=>f.home===team||f.away===team).length&&new Set(scheduleIds).size===scheduleIds.length,`Club schedule ${team}:${scheduleIds.length} exact unique fixtures across sources`);
  const details=schedule.slice(schedule.indexOf('<details class="schedule-details"'));
  check(scheduleIds.length>0&&schedule.includes('class="fixture-main"')&&!schedule.includes('(UK time)')&&schedule.includes('<summary>Workload & schedule details</summary>')&&[...details.matchAll(/data-club-gap="([^"]*)"/g)].length===scheduleIds.length&&!schedule.includes('<details class="schedule-details" open'),`Lean club schedule ${team}:${scheduleIds.length} matches retain gap evidence in collapsed details`);

 }
 check(renderedCells>0&&playerCells>0&&forecastCells>0&&summaryCells>0&&!scalarOff.length,`Club HTML:${renderedCells} performance cells,${playerCells} player values,${forecastCells} fates,${summaryCells} summaries equal source`,scalarOff.slice(0,6).join(';'));
 const forecast=X.clubForecastComparisonHtml(['Arsenal','Chelsea'],primary);let comparisonForecasts=0,forecastOff=0;
 for(const m of forecast.matchAll(/data-club-forecast="([^"]+)" data-value="([^"]*)"/g)){const [team,key]=m[1].split('|'),block=RESULT.leagues.find(b=>b.competition===primary),row=block.teams.find(t=>t.team===team),expected=key==='pos'?X.placesNow(block)?.[team]:key==='pts'?row.now?.pts??row.real?.pts:row[key],actual=m[2]===''?null:+m[2];comparisonForecasts++;if(actual!==(expected??null))forecastOff++;}
 check(comparisonForecasts>0&&!forecastOff&&forecast.includes('data-mv-metric'),`Club forecast comparison:${comparisonForecasts} aligned source values retain rolling-window delta hooks`);
 const normal=Workspace.clubComparison(RESULT,pool,['Arsenal','Chelsea'],{competition:primary}),reverse=Workspace.clubComparison(RESULT,pool,['Chelsea','Arsenal'],{competition:primary});
 check(normal.valid&&reverse.valid&&JSON.stringify(normal.rows[0])===JSON.stringify(reverse.rows[1])&&JSON.stringify(normal.rows[1])===JSON.stringify(reverse.rows[0]),'Club comparison:2 reversed columns retain every source value');
 check(!Workspace.clubComparison(RESULT,pool,['Arsenal','Real Madrid'],{competition:primary}).valid,'Club comparison:1 cross-league club refuses a local competition scope');
 const allRows=Workspace.clubMatches(RESULT,pool,'Arsenal',{competition:'all'}),leagueRows=Workspace.clubMatches(RESULT,pool,'Arsenal',{competition:'leagues'});
 const domestic=new Set(RESULT.leagues.map(b=>b.competition)),expectedDomestic=allRows.filter(f=>domestic.has(f.competition));
 check(allRows.length>leagueRows.length&&leagueRows.length>0&&JSON.stringify(leagueRows.map(Workspace.clubFixtureId))===JSON.stringify(expectedDomestic.map(Workspace.clubFixtureId)),'Club scope:All competitions includes retained cup/UEFA matches; Domestic leagues selects exact domestic fixture identities');
 for(const scope of ['all','leagues',primary]){
  X.CLUB_CHART='trajectory';const markup=X.clubChartHtml(['Arsenal','Chelsea'],pool,scope);
  check((markup.match(/\bdata-chart-picker\b/g)||[]).length===1&&(markup.match(/\bdata-performance-root\b/g)||[]).length===1&&markup.includes('data-performance-hosted="1"')&&markup.includes('data-performance-comp="'+scope+'"')&&!markup.includes('studio-competition')&&!markup.includes('studio-venue'),'Club host:'+scope+' keeps one Chart picker and one exact hosted evidence scope');
 }
 const actualRows=Array.from({length:6},(_,i)=>({competition:primary,home:'Actual A',away:'Actual B',kickoff:'2026-10-'+String(i+10).padStart(2,'0')+' 15:00:00',result:[1,0],xg:i===4?null:[i+1,1]}));
 const actualPool=Workspace.clubFixturePool(RESULT,null,{fixtures:actualRows}),form=Workspace.clubFormComparison(RESULT,actualPool,['Actual A']);
 check(form.source.get('Actual A').length===6&&form.vals.get('Actual A').at(-1)===null&&form.source.get('Actual A')[3].value===1.5,'Club actual window:6 played matches retain a missing-xG fifth fixture; latest last5 stays unavailable instead of reaching for older evidence');
 const legacyForm=X.teamFormData('Actual A',actualRows.slice().reverse().map(f=>({f})));
 check(legacyForm.length===6&&legacyForm.at(-1).for===null&&legacyForm.at(-1).against===null&&legacyForm.at(-1).known===4&&legacyForm.at(-1).window.length===5&&legacyForm.at(-1).window[0].includes('2026-10-11'),'Legacy team Form:unordered six-match source sorts kickoff instants and retains the missing fixture inside exact last5');
 const badForm=structuredClone(legacyForm);badForm.at(-1).for=3;const validActualWindow=rows=>rows.at(-1).for===null&&rows.at(-1).window.length===5&&rows.at(-1).known===4;
 check(validActualWindow(legacyForm)&&!validActualWindow(badForm),'Actual-window fault:deliberately substituting an older covered value fails the missing-component check');
 const ukRows=[{...actualRows[0],competition:'Italian Serie A',kickoff:'2026-10-14 00:30:00'},{...actualRows[1],competition:'Italian Serie A',away:'Actual C',kickoff:'2026-10-14 01:30:00'}],ukPool=Workspace.clubFixturePool(RESULT,null,{fixtures:ukRows}),ukSelected=Workspace.clubMatches(RESULT,ukPool,'Actual A',{since:'2026-10-13'});
 check(Workspace.clubDay(ukRows[0])==='2026-10-13'&&Workspace.clubDay(ukRows[1])==='2026-10-14'&&ukSelected.length===1&&ukSelected[0].kickoff===ukRows[1].kickoff,'Club UK dates:continental midnight fixture belongs to prior UK day; shared calendar boundary selects exact matching fixture');
 const eliminatedResult={...RESULT,leagues:[],uefa:[],cups:[{competition:'Retained Cup',teams:[{team:'Survivor'}]}]},eliminatedPool=Workspace.clubFixturePool(eliminatedResult,null,{fixtures:[{...actualRows[0],competition:'Retained Cup',home:'Eliminated A',away:'Eliminated B'}]});
 check(Workspace.clubComparison(eliminatedResult,eliminatedPool,['Eliminated A','Eliminated B'],{competition:'Retained Cup'}).valid,'Club eliminated entrants:played cup membership remains eligible after forecast survivor lists shrink');
 const local=Workspace.clubStrength(RESULT,'Arsenal',primary),global=Workspace.clubStrength(RESULT,'Arsenal'),factor=RESULT.ratings.rel[primary].now;
 check(local.scale===primary&&global.scale==='all'&&local.elo===global.elo&&Math.abs(local.att-global.att*factor[0])<1e-12&&Math.abs(local.def-global.def*factor[1])<1e-12,'Club comparison:4 local/global ATT/DEF values use the declared scale; Elo unchanged');
 let caught=false;try{const damaged={...global,att:local.att};if(Math.abs(damaged.att-RESULT.ratings.teams.find(t=>t.team==='Arsenal').att)>1e-12)throw Error('wrong cross-league scale');}catch{caught=true;}
 check(caught&&factor[0]!==1,'Club scale fault:1 deliberate locally-scaled cross-league value is caught');
 const cup=pool.fixtures.find(f=>f.result&&RESULT.cups.some(b=>b.competition===f.competition)),base=Workspace.clubPerformance(RESULT,pool,cup.home),duplicate=Workspace.clubFixturePool(RESULT,GWD,{fixtures:[...agenda.fixtures,cup]},MATCHES.fixtures),again=Workspace.clubPerformance(RESULT,duplicate,cup.home);
 check(base.pl===again.pl&&base.gf===again.gf&&base.ga===again.ga&&duplicate.duplicates>pool.duplicates,'Club duplicate input:1 extra played cup row cannot change PL/GF/GA');
 let doubleCaught=false;const damagedPool={...pool,fixtures:[...pool.fixtures,cup]};try{const bad=Workspace.clubPerformance(RESULT,damagedPool,cup.home);if(bad.pl!==base.pl)throw Error('duplicate');}catch{doubleCaught=true;}
 check(doubleCaught&&base.pl>0,'Club double-count fault:1 extra canonical cup match fails the independent PL identity');
 const sourceSquad=Workspace.clubPlayerContributions(RESULT,PLAYERS,'Arsenal');let sourceContributions=0;
 for(const row of sourceSquad.rows)for(const key of ['matches','minutes','goals','xg','assists','shots']){sourceContributions++;const want=row.parts.every(p=>Number.isFinite(p.source[key]))?row.parts.reduce((sum,p)=>sum+p.source[key],0):null;if(row[key]!==want)scalarOff.push('player contribution '+row.id+'/'+key);}
 check(sourceContributions>0&&!scalarOff.length,`Club squad:${sourceContributions} strict metric sums equal disjoint club/competition contributions; unknowns preserved`);
 const peers=Workspace.clubPeers(RESULT,pool,'Arsenal',{competition:primary});let peerOff=0;
 for(const row of peers.rows){const expected=Math.sqrt(peers.used.reduce((sum,i)=>sum+((row.values[i]-peers.target.values[i])/peers.sd[i])**2,0)/peers.used.length);if(Math.abs(row.distance-expected)>1e-12)peerOff++;}
 check(peers.rows.length>0&&peerOff===0&&peers.rows.every((r,i)=>!i||r.distance>=peers.rows[i-1].distance),`Club peers:${peers.rows.length} ranks equal transparent standardized distance over${peers.used.length} covered features`);
 const synthetic={...RESULT,as_of:'2026-10-21'},f={competition:'Cup',home:'A',away:'B',kickoff:'2026-10-18 15:00:00',result:[2,0],xg:[1,.5],minutes:90};
 const missing=Workspace.clubPerformance(synthetic,Workspace.clubFixturePool(synthetic,null,{fixtures:[f,{...f,kickoff:'2026-10-19 15:00:00',xg:null}]}),'A');
 check(missing.xg===null&&missing.n_xg===1&&missing.pl===2&&missing.xgf_rate===1,'Club missing xG:2 matches retain strict unavailable total and1 covered-match rate');
 const conditional=Workspace.clubFixturePool(synthetic,null,{fixtures:[f,{...f,kickoff:'2026-10-24 15:00:00',result:null,p_occurs:.5},{...f,kickoff:'2026-10-27 15:00:00',result:null}]}),schedule=Workspace.clubSchedule(synthetic,conditional,'A');
 check(schedule.length===2&&schedule[1].gap===null&&schedule[1].gap_blocked&&conditional.conditional.length===1,'Club schedule:1 contingent knockout pairing cannot invent a rest interval');
 const stages=Workspace.clubConditionalStages(RESULT,'Arsenal');
 check(stages.length>0&&stages.every(r=>r.date===null&&r.opponent===null&&r.probability>0&&r.probability<1),`Club knockout possibilities:${stages.length} source stage chances have no invented date/opponent`);
 const oldGW=X.GW;let poolBuilds=0;X.WORKSPACE={...Workspace,clubFixturePool(...args){poolBuilds++;return Workspace.clubFixturePool(...args);}};
 const cached=X.clubPool(),repeat=X.clubPool();let cacheOK=cached===repeat&&poolBuilds===1;
 X.GW={...oldGW};const replaced=X.clubPool();cacheOK&&=replaced!==cached&&poolBuilds===2&&replaced.fixtures.length===cached.fixtures.length;
 const injected={...pool.fixtures.find(f=>f.result),home:'Cache test home',away:'Cache test away'},revision={...agenda,fixtures:[...agenda.fixtures,injected]};X.AGENDA_CACHE.set(RESULT.source.projection_sha256,revision);
 const fresh=X.clubPool();cacheOK&&=poolBuilds===3&&fresh.fixtures.some(f=>f.home===injected.home)&&!cached.fixtures.some(f=>f.home===injected.home);
 X.AGENDA_CACHE.set(RESULT.source.projection_sha256,agenda);X.clubPool();cacheOK&&=poolBuilds===4;
 X.MATCHES={...MATCHES};X.clubPool();cacheOK&&=poolBuilds===5;
 X.RESULT={...RESULT};X.clubPool();cacheOK&&=poolBuilds===6;
 check(cacheOK,'Club pool cache:6 builds account for stable reuse plus GW/agenda/removal/match/snapshot source replacement; stale pool misses injected fixture');
 X.RESULT=RESULT;X.GW=oldGW;X.MATCHES=MATCHES;X.WORKSPACE=Workspace;
 const requested=Workspace.fixtureSentence({...f,result:undefined,home_goals:'2.0',away_goals:'0.0'},'Cup');
 check(requested==='Sun, 18 Oct 2026, 16:00 · Cup · A 2 - B 0'&&!Workspace.fixtureSentence({...f,result:null,home_goals:'0.0',away_goals:'0.0'},'Cup').includes('A 0'),'Fixture summaries:2 played/upcoming rows use requested UK-time sentence and integer scores');
 const sources=truth||agenda.fixtures.filter(f=>f.result),last=sources.filter(f=>f.home==='Arsenal'||f.away==='Arsenal').slice(-1)[0],before=Workspace.clubWorkload(RESULT,pool,'Arsenal',14),future={...last,kickoff:'2099-01-01 15:00:00'};
 check(Workspace.clubFixturePool(RESULT,null,{fixtures:[future]}).fixtures.length===0&&before.matches===Workspace.clubPerformance(RESULT,pool,'Arsenal',{since:new Date(Date.parse(RESULT.as_of+'T00:00:00Z')-14*86400000).toISOString().slice(0,10)}).pl,'Club cutoff/workload:1 future result excluded;14-day count equals source-window match selection');
 X.CLUB_SECTION='season';X.CLUB_SCOPE='all';X.CLUB_COMPARE=[];X.WORKSPACE=null;
}else console.log('  skip    Club command centre source checks (no agenda fixture supplied)');


// Task4 first slice: identities/stints, strict xA, matched rates, contribution shares and routes.
check(Workspace.normaliseSearch('Ødegaard')==='odegaard'&&Workspace.normaliseSearch('Müller')==='muller'&&Workspace.normaliseSearch('Łukasz')==='lukasz','Player search:3 Scandinavian/diacritic names normalize consistently');
if(PLAYERS&&Object.values(PLAYERS.competitions||{}).some(b=>b.players?.length)){
 X.WORKSPACE=Workspace;X.WORKSPACE_PREFS=Workspace.emptyPreferences();X.PLAYERS=PLAYERS;X.PLAYER_TEAM='all';X.PLAYER_SCOPE='all';X.PLAYER_QUERY='';X.PLAYER_DISCOVERY_MIN=180;
 const index=Workspace.playerEvidenceIndex(RESULT,PLAYERS);let parts=0,metrics=0,off=[];
 for(const entity of index.entities){
  const profile=Workspace.playerProfileEvidence(RESULT,PLAYERS,entity.id);
  for(const part of profile.parts){parts++;for(const [key] of Workspace.PROFILE_METRICS){const ev=Workspace.contributionEvidence([part],key),want=part.source[key]??null;metrics++;if(ev.total!==want||ev.known+ev.unknown!==ev.appearances)off.push(entity.id+'/'+part.team+'/'+key);}}
 }
 check(index.entities.length>0&&parts>0&&metrics>0&&!off.length,`Player profiles:${index.entities.length} identities/${parts} disjoint stints/${metrics} strict metrics and known+unknown accounting equal payload`,off.slice(0,5).join(';'));
 check(index===Workspace.playerEvidenceIndex(RESULT,PLAYERS)&&index!==Workspace.playerEvidenceIndex({...RESULT},PLAYERS),'Player evidence cache:2 stable-reference/snapshot-replacement identities');
 let overviewCells=0;
 for(const sort of ['goals','xg','assists','xa','ga','xga']){
  const data=Workspace.playerOverview(RESULT,PLAYERS,{sort,limit:Infinity});
  check(data.rows.length===index.entities.length&&data.rows.every((r,i)=>r.metrics.ga===(r.metrics.goals!=null&&r.metrics.assists!=null?r.metrics.goals+r.metrics.assists:null)&&(!i||(data.rows[i-1].metrics[sort]??-1)>=(r.metrics[sort]??-1))),`Player overview ${sort}:${data.rows.length} identities retained; G/A=goals+assists and descending known-first order`);
 }
 const overview=Workspace.playerOverview(RESULT,PLAYERS),overviewHtml=X.playerOverviewHtml(),overviewRows=[...overviewHtml.matchAll(/<tr data-overview-player="([^"]+)">([\s\S]*?)<\/tr>/g)];
 const overviewOK=rows=>rows.length===overview.rows.length&&rows.every((m,i)=>{const r=overview.rows[i],cells=[...m[2].matchAll(/data-overview-stat="([^"]+)" data-value="([^"]*)"/g)];return m[1]===r.id&&cells.length===7&&cells.every(c=>(c[2]===''?null:+c[2])===r.metrics[c[1]]);});
 check(overviewRows.length>0&&overviewOK(overviewRows),`Overview HTML:${overviewRows.length*7} exact minute/goal/xG/assist/xA/G/A/xG/A cells`);
 const brokenOverview=overviewRows.map(m=>[...m]);brokenOverview[0][2]=brokenOverview[0][2].replace(/(data-overview-stat="ga" data-value=")[^"]*"/,'$1999"');
 check(!overviewOK(brokenOverview),'Overview fault:1 shifted G/A value rejected');
 const overviewRoute=new URLSearchParams(Workspace.routeHash({TAB:RESULT.leagues[0].competition,WORKSPACE:true,WORKSPACE_SECTION:'players',RESULT,PLAYER_OVERVIEW_SORT:'ga',selectedView:'stats',kind:'league',DWIN_DEFAULT:'1w',DWIN:'1w',GWSEL:{},PATHSEL:{}}));
 check(overviewRoute.get('pview')==='overview'&&overviewRoute.get('psort')==='ga','Overview route:default overview and selected G/A sort retained');
 let creatorCells=0;
 for(const metric of ['xa','chances_created','assists'])for(const unit of ['total','rate']){
  X.PLAYER_DISCOVERY_STAT=metric;X.PLAYER_DISCOVERY_UNIT=unit;
  const data=Workspace.creatorDiscovery(RESULT,PLAYERS,{metric,unit,minimum:180}),html=X.playerDiscoveryHtml(),cells=[...html.matchAll(/data-creator="([^"]+)" data-creator-value="([^"]+)"/g)];creatorCells+=cells.length;
  check(cells.length===data.rows.length&&cells.every((m,i)=>m[1]===data.rows[i].id&&Math.abs(+m[2]-data.rows[i].value)<1e-10)&&data.rows.every(r=>r.evidence.complete&&r.minutes.total>=180&&(unit==='total'||r.minutes.complete)),`Creator HTML ${metric}/${unit}:${cells.length} exact values, complete coverage and matched minutes`);
 }
 if(creatorCells>0)check(true,`Creators coverage:${creatorCells} rendered nonempty leader values across6 metric/unit selections`);else console.log('  skip    nonempty creator coverage proof (snapshot has0 complete eligible values at180 minutes; empty-state identities checked)');
 const transferred=index.entities.find(e=>new Set(e.parts.map(p=>p.team)).size>1)||index.entities[0];X.PLAYER_PROFILE_ID=transferred.id;X.PLAYER_SCOPE='all';
 const profile=Workspace.playerProfileEvidence(RESULT,PLAYERS,transferred.id),html=X.playerProfilePageHtml(),cells=[...html.matchAll(/data-profile-metric="([^"]+)" data-total="([^"]*)" data-observed="([^"]*)" data-known="([^"]*)" data-appearances="([^"]*)"/g)],expected=[...profile.stints.map(s=>s.metrics),profile.metrics].flatMap(metrics=>Workspace.PROFILE_METRICS.map(([key])=>({key,...metrics[key]})));
 const profileCellsOK=rows=>rows.length===expected.length&&rows.every((m,i)=>{const r=expected[i];return m[1]===r.key&&(m[2]===''?null:+m[2])===r.total&&(m[3]===''?null:+m[3])===r.observed&&+m[4]===r.known&&+m[5]===r.appearances;});
 check(profileCellsOK(cells)&&profile.stints.length>0,`Player profile HTML:${cells.length} exact transfer-stint/total/observed/coverage cells`);
 const brokenCells=cells.map(c=>[...c]);brokenCells[0][2]=String((+brokenCells[0][2]||0)+1);check(!profileCellsOK(brokenCells),'Player profile fault:1 shifted displayed total rejected');
 for(const metric of ['minutes','goals','xg','xa','chances_created']){
  X.PLAYER_SQUAD_TEAM='Arsenal';X.PLAYER_SQUAD_METRIC=metric;
  const data=Workspace.squadContributionEvidence(RESULT,PLAYERS,'Arsenal',{metric}),markup=X.playerSquadPageHtml(),rows=[...markup.matchAll(/data-squad-player="([^"]+)" data-squad-observed="([^"]*)" data-squad-share="([^"]*)"/g)],sum=rows.reduce((s,m)=>s+(m[3]===''?0:+m[3]),0);
  check(rows.length===data.rows.length&&rows.every((m,i)=>m[1]===data.rows[i].id&&(m[2]===''?null:+m[2])===data.rows[i].evidence.observed&&(m[3]===''?null:+m[3])===data.rows[i].share)&&(data.denominator>0?Math.abs(sum-1)<1e-10:sum===0),`Squad HTML ${metric}:${rows.length} source contributions; shares partition positive known denominator`);
 }
 const sample={matches:1,minutes:90,xa:2,chances_created:3,assists:1,goals:1,xg:.5,shots:2,known:{minutes:1,xa:1,chances_created:1,assists:1,goals:1,xg:1,shots:1}},missing={...sample,xa:null,known:{...sample.known,xa:0}},synthetic={season:RESULT.params.season,as_of:RESULT.as_of,competitions:{Test:{players:[{id:'test1',name:'Same Name',teams:['A','B'],...sample,xa:999,by_team:{A:sample,B:missing}},{id:'test2',name:'Same Name',teams:['B'],...sample,xa:0,known:{...sample.known,xa:1},by_team:{B:{...sample,xa:0}}}]}}};
 const moved=Workspace.playerProfileEvidence(RESULT,synthetic,'player:fotmob:test1'),a=Workspace.playerProfileEvidence(RESULT,synthetic,'player:fotmob:test1',{team:'A'}),b=Workspace.playerProfileEvidence(RESULT,synthetic,'player:fotmob:test1',{team:'B'});
 check(moved.metrics.xa.total===null&&moved.metrics.xa.observed===2&&moved.metrics.xa.known===1&&moved.metrics.xa.unknown===1&&a.metrics.xa.total===2&&b.metrics.xa.total===null,'Player transfer/unknown guards:2 stints never use pooled999; unknown xA stays unknown with separate known2');
 const missingAssist={...sample,assists:null,known:{...sample.known,assists:0}},unknownOverview=Workspace.playerOverview(RESULT,{...synthetic,competitions:{Test:{players:[{id:'unknown',name:'Unknown',teams:['A'],by_team:{A:missingAssist}}]}}});
 check(unknownOverview.rows.length===1&&unknownOverview.rows[0].metrics.goals===1&&unknownOverview.rows[0].metrics.assists===null&&unknownOverview.rows[0].metrics.ga===null,'Overview missing assist:1 player remains visible with known goal; unknown assist and G/A stay unavailable');
 const rate=Workspace.contributionRate(moved.parts,'xa'),matched=Workspace.contributionRate(a.parts,'xa'),badMinutes=Workspace.contributionRate([{source:{...sample,minutes:null,known:{...sample.known,minutes:0}}}],'xa');
 check(rate.value===null&&matched.value===2&&badMinutes.value===null,'Player per90 guards:3 complete/missing numerator/missing minute cases use exactly matched appearances');
 const zero=Workspace.squadContributionEvidence(RESULT,{...synthetic,competitions:{Test:{players:[{id:'zero',name:'Zero',teams:['B'],by_team:{B:{...sample,xa:0}}}]}}},'B',{metric:'xa'});
 check(zero.denominator===0&&zero.rows[0].share===null&&zero.top3===null,'Squad zero guard:1 genuine zero denominator cannot become a percentage');
 const unavailable=Workspace.playerEvidenceIndex(RESULT,{...PLAYERS,as_of:'1900-01-01'}),unknownClub=Workspace.playerProfileEvidence(RESULT,synthetic,'player:fotmob:test1',{team:'Not a stint'}),identities=Workspace.playerEvidenceIndex(RESULT,synthetic).entities;
 check(!unavailable.available&&!unavailable.entities.length&&unknownClub.parts.length===0&&unknownClub.metrics.xa.total===null&&identities.length===2,'Player guards:3 wrong-cutoff/absent-club/same-name cases retain exact identity and unknown scope');
 const state={TAB:RESULT.leagues[0].competition,WORKSPACE:true,WORKSPACE_SECTION:'players',RESULT,COLUMN_PROFILE:'forecast',PLAYER_WORKSPACE_VIEW:'profile',PLAYER_SCOPE:'Test',PLAYER_PROFILE_ID:transferred.id,PLAYER_EVIDENCE_TEAM:'A',PLAYER_DISCOVERY_STAT:'chances_created',PLAYER_DISCOVERY_UNIT:'rate',PLAYER_DISCOVERY_MIN:450,PLAYER_QUERY:'Same',PLAYER_SQUAD_TEAM:'Arsenal',PLAYER_SQUAD_METRIC:'minutes',selectedView:'stats',kind:'league',HUBSEL:'players',DWIN_DEFAULT:'1w',DWIN:'1w',GWSEL:{},PATHSEL:{}};
 const saved=new URLSearchParams(Workspace.routeHash(state));check(saved.get('pview')==='profile'&&saved.get('profile')===transferred.id&&saved.get('pscope')==='Test'&&saved.get('pclub')==='A'&&saved.get('pmetric')==='chances_created'&&saved.get('punit')==='rate'&&saved.get('pfloor')==='450'&&saved.get('pquery')==='Same'&&saved.get('squad')==='Arsenal'&&saved.get('smetric')==='minutes','Player saved route:10 exact profile/discovery/squad selections serialize without dropping scope');
 X.WORKSPACE=null;
}else console.log('  skip    Task4 player discovery/profile/squad checks (snapshot has no player evidence)');


// Home, player comparison and Tactical Atlas: rendered identities and deliberate faults.
{
 check(Workspace.teamCode('FC Bayern München')==='BAY'&&Workspace.teamCode('Arsenal')==='ARS'&&Workspace.teamCode('Paris Saint-Germain')==='PSG','Shared codes:3 existing compact names produce BAY/ARS/PSG');
 const compact=Workspace.fixtureHtml({home:'FC Bayern München',away:'Arsenal',competition:'UEFA Champions League',kickoff:'2026-10-21 21:00:00',result:[2,2]});
 check(compact.includes('>BAY</abbr>')&&compact.includes('>ARS</abbr>')&&compact.includes('title="FC Bayern München"')&&compact.includes('aria-label="Arsenal"')&&compact.includes('class="fixture-team-name">Arsenal'),'Compact fixtures:2 display codes retain full names and accessible labels');
 check(JSON.stringify(Workspace.SECTIONS.map(([,name])=>name))===JSON.stringify(['Home','Comps','Clubs','Players','Explore'])&&Workspace.sectionFromRoute('#section=matches')==='home'&&Workspace.sectionFromRoute('#tab=Big+matches')==='home'&&Workspace.sectionFromRoute('#section=comps')==='races','Navigation:5 destinations;3 legacy/new aliases resolve without a Matches tab');
 if(centrePath&&centrePath!=='-'){
  const e=JSON.parse(readFileSync(centrePath,'utf8'));X.WORKSPACE=Workspace;X.MC=MatchCentre;X.WORKSPACE_PREFS=Workspace.emptyPreferences();
  const day=e.agenda.fixtures.find(f=>f.kickoff.slice(0,10)>RESULT.as_of)?.kickoff.slice(0,10)||RESULT.as_of;X.AGENDA_DATE=day;X.HOME_MATCH='';X.HOME_LIMIT=5;
  const rows=X.homeRows(e.agenda),html=X.homeHtml(e.agenda),ids=[...html.matchAll(/data-home-fixture="([^"]+)"/g)].map(m=>m[1]);
  check(rows.length>0&&ids.length===Math.min(5,rows.length)&&ids.every((id,i)=>id===Workspace.esc(rows[i].id))&&html.includes('data-home-preview="'+Workspace.esc(rows[0].id)+'"')&&[...html.matchAll(/data-centre="/g)].length===ids.length&&!html.includes('home-plan'),`Home:${ids.length}/${rows.length} first chronological fixtures,first inline preview,1 Match Centre button per row,no viewing plan`);
  X.HOME_LIMIT=Infinity;const expanded=X.homeHtml(e.agenda);check([...expanded.matchAll(/data-home-fixture="/g)].length===rows.length,`Home More:${rows.length} exact day fixtures revealed`);X.HOME_LIMIT=5;
  for(const data of e.atlases||[]){
   let cases=0;
   for(const side of ['for','against'])for(const venue of ['all','home','away']){
    const options={side,venue},selection=MatchCentre.atlasSelection(data,options),expected=data.matches.filter(m=>venue==='all'||(m.fixture.home===data.team?'home':'away')===venue).filter(m=>m.coverage?.shotmap).flatMap(m=>m.shots.filter(s=>!s.own_goal&&(side==='for'?m.fixture[s.side]===data.team:m.fixture[s.side]!==data.team)).map(s=>({...s,uid:m.fixture.id+'|'+s.id})));
    const expectedIds=expected.map(s=>s.uid).sort(),actual=selection.shots.map(s=>s.uid).sort();
    check(JSON.stringify(actual)===JSON.stringify(expectedIds)&&Math.abs(selection.knownXg-expected.reduce((a,s)=>a+(s.xg??0),0))<1e-9,`Atlas ${data.team}/${side}/${venue}:${actual.length} exact eligible shot IDs and source xG sum`);
    const plot=MatchCentre.atlasPitchHtml(selection),marks=[...plot.matchAll(/data-atlas-shot="([^"]+)" data-atlas-x="([^"]+)" data-atlas-y="([^"]+)"/g)],geometryOK=items=>items.length===selection.located&&items.every(m=>{const s=expected.find(s=>Workspace.esc(s.uid)===m[1]);return s&&+m[2]===s.x&&Math.abs(+m[3]-(68-s.y))<1e-10;});
    check(geometryOK(marks),`Atlas geometry ${data.team}/${side}/${venue}:${marks.length} canonical rightward coordinates`);
    if(marks.length){const bad=marks.map(m=>[...m]);bad[0][3]=String(+bad[0][3]+1);check(!geometryOK(bad),'Atlas geometry fault:1 shifted source y rejected');}
    const grid=MatchCentre.atlasPitchHtml(selection,{chart:'density'}),bins=[...grid.matchAll(/data-atlas-bin="([^"]+)" data-bin-count="([^"]+)" data-bin-xg="([^"]+)"/g)];
    const binsOK=items=>items.length===28&&items.every(m=>{const located=expected.filter(s=>s.x!=null&&s.y!=null),[col,row]=m[1].split('-').map(Number),source=located.filter(s=>Math.min(6,Math.floor(s.x/15))===col&&Math.min(3,Math.floor((68-s.y)/17))===row);return +m[2]===source.length&&Math.abs(+m[3]-source.reduce((n,s)=>n+(s.xg??0),0))<1e-9;});
    check(binsOK(bins)&&bins.reduce((n,m)=>n+ +m[2],0)===selection.located,`Atlas grid ${data.team}/${side}/${venue}:28 bins partition ${selection.located} located source attempts`);
    const broken=bins.map(m=>[...m]);broken[0][2]=String(+broken[0][2]+1);check(!binsOK(broken),'Atlas grid fault:1 shifted count rejected');
    const chosen=selection.bins.find(b=>b.count>0);if(chosen){const region=MatchCentre.atlasSelection(data,{...options,bin:chosen.id});check(region.shots.length===chosen.count&&region.shots.every(s=>s.bin===chosen.id),`Atlas region ${data.team}/${side}/${venue}:${chosen.count} attempts equal clicked cell`);}
    cases++;
   }
   const cutoff=data.matches[Math.floor(data.matches.length/2)]?.fixture.kickoff.slice(0,10),recent=MatchCentre.atlasSelection(data,{period:'window',since:cutoff}),before=MatchCentre.atlasSelection(data,{period:'before',since:cutoff}),all=MatchCentre.atlasSelection(data);
   check(recent.universe.length+before.universe.length===all.universe.length&&recent.matches.every(m=>m.fixture.kickoff.slice(0,10)>cutoff)&&before.matches.every(m=>m.fixture.kickoff.slice(0,10)<=cutoff),`Atlas windows ${data.team}:${all.universe.length} attempts partition before/after shared cutoff over ${cases} selectors`);
   const situation=all.universe.find(s=>s.situation)?.situation,typed=MatchCentre.atlasSelection(data,{type:situation});check(typed.shots.every(s=>s.situation===situation),`Atlas situation ${data.team}:${typed.shots.length} exact provider types`);
  }
  if(e.atlases?.length)check(e.atlases.length>0,`Atlas coverage:${e.atlases.length} independent club payloads`);else console.log('  skip    Atlas source fixtures (older fixture bundle lacks atlases)');
  X.WORKSPACE=null;
 }
 if(PLAYERS){
  const index=Workspace.playerEvidenceIndex(RESULT,PLAYERS),ids=Workspace.playerOverview(RESULT,PLAYERS,{limit:4}).rows.map(r=>r.id);X.WORKSPACE=Workspace;X.PLAYERS=PLAYERS;X.PLAYER_COMPARE=ids;X.PLAYER_SCOPE='all';X.PLAYER_EVIDENCE_TEAM='all';X.PLAYER_QUERY='';X.PLAYER_DISCOVERY_MIN=180;
  for(const unit of ['total','rate']){
   X.PLAYER_COMPARE_UNIT=unit;const data=Workspace.playerComparison(RESULT,PLAYERS,ids,{unit,minimum:180}),html=X.playerComparisonHtml(),cells=[...html.matchAll(/data-player-compare="([^"]+)" data-compare-metric="([^"]+)" data-value="([^"]*)"/g)];
   const exact=items=>items.length===ids.length*Workspace.COMPARISON_METRICS.length&&items.every(m=>{const r=data.rows.find(r=>r.id===m[1]);return r&&(m[3]===''?null:+m[3])===r.metrics[m[2]].value;});
   check(exact(cells)&&data.rows.length===4,`Player comparison ${unit}:${cells.length} rendered metric values retain source scope/order`);
   const broken=cells.map(m=>[...m]);broken[0][3]='999';check(!exact(broken),'Comparison fault:1 shifted displayed metric rejected');
   let n=0;for(const row of data.rows)for(const [k,e] of Object.entries(row.metrics)){
    const parts=index.byId.get(row.id).parts,keys=k==='ga'?['goals','assists']:k==='xga'?['xg','xa']:[k],inputs=keys.map(key=>Workspace.contributionEvidence(parts,key)),mins=Workspace.contributionEvidence(parts,'minutes'),total=inputs.every(v=>v.complete)?inputs.reduce((s,e)=>s+e.total,0):null,want=unit==='total'?total:total!=null&&mins.complete&&mins.total>=180?90*total/mins.total:null;
    check(e.value===want,`Comparison source ${unit}/${row.id}/${k}:1 complete numerator and matched minute identity`);n++;
   }
   check(n>0,`Comparison accounting ${unit}:${n} nonempty identities`);
  }
  const cached=Workspace.playerComparison(RESULT,PLAYERS,ids),cachedAgain=Workspace.playerComparison(RESULT,PLAYERS,ids),different=Workspace.playerComparison(RESULT,PLAYERS,ids,{unit:'rate'}),replaced=Workspace.playerComparison({...RESULT},PLAYERS,ids);
  check(cached===cachedAgain&&cached!==different&&cached!==replaced,'Comparison cache:3 unchanged/filter/source reference cases reuse or invalidate exactly');
  const route=new URLSearchParams(Workspace.routeHash({TAB:RESULT.leagues[0].competition,WORKSPACE:true,WORKSPACE_SECTION:'players',RESULT,PLAYER_WORKSPACE_VIEW:'compare',PLAYER_COMPARE:ids,PLAYER_COMPARE_UNIT:'rate',PLAYER_OVERVIEW_SORT:'xga',selectedView:'stats',kind:'league',GWSEL:{},PATHSEL:{}}));check(route.get('pc')===JSON.stringify(ids)&&route.get('pcunit')==='rate'&&route.get('psort')==='xga','Comparison saved route:4 exact ordered IDs,per90,xG/A sort retained');
  X.WORKSPACE=null;
 }
}

// Independent miniature full-world orders exercise available and unavailable Race Room views.
{
 const names=['Alpha','Beta','Gamma'],orders=[[1,2,3],[1,3,2],[3,1,2],[2,3,1]],n=3,w=orders.length;
 const r={schema:1,worlds:w,teams:names,gap_offset:-2,
   gap_counts:names.map(()=>names.map(()=>Array(5).fill(0))),position_counts:names.map(()=>Array(3).fill(0))};
 for(const order of orders)for(let i=0;i<n;i++){
  r.position_counts[i][order[i]-1]++;
  for(let j=0;j<n;j++)r.gap_counts[i][j][order[j]-order[i]+2]++;
 }
 const block={competition:'English Premier League',rivals:r,teams:names.map((team,i)=>({team,mean_pos:orders.reduce((s,o)=>s+o[i],0)/w}))};
 const old={...X.VIZOPT};X.VIZOPT.rivalTeam='Alpha';X.VIZOPT.rivalOpponent='Beta';
 const d=X.rivalData(block),render=X.vizHtml(block,'league','rivals');
 check(!d.error&&d.above[0][1]===3&&d.above[1][0]===1&&d.expected[0]===1.75&&
   (render.match(/data-rival-pair=/g)||[]).length===6&&(render.match(/<option /g)||[]).length===5&&
   render.includes('Finishing gap distribution')&&render.includes('4 simulated worlds')&&render.includes('75.0%'),
   'Race Room:4 independently specified worlds give6 selectable pair cells,3/4 Alpha above Beta,expected rank1.75 and full gap detail');
 const missing=X.vizRivals({...block,rivals:undefined});
 check(missing.includes('no full-world rival evidence')&&!missing.includes('data-rival-matrix'),
   'Race Room:old snapshots show an honest unavailable state without substituting sample seasons');
 const faults=[];
 for(const fault of ['count','rank','schema','teams','negative','fraction','shape','mirror']){
  const b=structuredClone(block);
  if(fault==='count')b.rivals.gap_counts[0][1][4]++;
  if(fault==='rank')b.teams[0].mean_pos=2.5;
  if(fault==='schema')b.rivals.schema=99;
  if(fault==='teams')b.rivals.teams=['Alpha','Beta','Beta'];
  if(fault==='negative')b.rivals.gap_counts[0][1][0]=-1;
  if(fault==='fraction')b.rivals.gap_counts[0][1][0]=.5;
  if(fault==='shape')b.rivals.position_counts.pop();
  if(fault==='mirror'){b.rivals.gap_counts[0][1][3]--;b.rivals.gap_counts[0][1][4]++;}
  if(!X.rivalData(b).error||!X.vizRivals(b).includes('role="alert"'))faults.push(fault);
 }
 check(!faults.length,'Race Room:8 deliberate source count/rank/schema/identity/shape faults remain visible',faults.join(','));
 X.VIZOPT.rivalTeam='Gone';X.VIZOPT.rivalOpponent='Gone';
 const fallback=X.vizRivals(block);
 check(fallback.includes('Alpha v Beta')&&X.vizGroups('league').some(([,a])=>a.some(([k])=>k==='rivals'))&&
   !X.vizGroups('uefa').some(([,a])=>a.some(([k])=>k==='rivals')),
   'Race Room:stale club controls fall back to distinct identities;no domestic finishing-order chart on UEFA');
 Object.assign(X.VIZOPT,old);
}

{
 const old={...X.VIZOPT};
 const block={competition:'English Premier League',teams:[{team:'Alpha',mean_pos:1,p_win:.5,p_ucl:.75,p_uel:0,p_uecl:0},{team:'Beta',mean_pos:2,p_win:.25,p_ucl:0,p_uel:.25,p_uecl:.25},{team:'Gamma',mean_pos:3,p_win:.25,p_ucl:0,p_uel:0,p_uecl:0}],qualification:{eps:1}};
 const g={rounds:3,teams:['Alpha','Beta','Gamma'],clinch:[[0,1,.25],[0,3,.25],[1,2,.25],[2,3,.25]],fixtures:[]};
 X.VIZOPT.timingRound='2';const d=X.timingData(block,g),html=X.vizTiming(block,g);
 check(!d.error&&d.settled.join(',')==='0,0.25,0.5,1'&&d.perClub.get('Alpha')[2]===.25&&
  html.includes('still open 50.0%')&&html.includes('data-title-timing')&&html.includes('no calendar clinch dates'),
  'Race Room Timing:4 independent title/round outcomes give50% settled byGW2 and25% Alpha unresolved title mass');
 const faults=[];
 for(const mode of ['probability','round','duplicate','missing','marginal']){
  const bad=structuredClone(g);if(mode==='probability')bad.clinch[0][2]=1.1;if(mode==='round')bad.clinch[0][1]=4;
  if(mode==='duplicate')bad.clinch.push([...bad.clinch[0]]);if(mode==='missing')bad.clinch.pop();if(mode==='marginal')bad.clinch[0][0]=1;
  if(!X.timingData(block,bad).error)faults.push(mode);
 }
 check(!faults.length&&X.vizTiming(block,null).includes('no title-timing evidence'),
  'Race Room Timing:5 invalid population/round/marginal faults rejected;missing source stays unavailable',faults.join(','));
 const routes=['league','cup','league_cup','ucl_holder','uel_holder','uecl_holder','eps'];
 const empty=()=>[Array(7).fill(0),Array(7).fill(0),Array(7).fill(0)];
 const counts={Alpha:empty(),Beta:empty(),Gamma:empty(),Outside:empty()};counts.Alpha[0][0]=2;counts.Alpha[0][6]=1;counts.Beta[1][1]=1;counts.Beta[2][2]=1;counts.Outside[1][1]=1;
 block.entry_routes={schema:1,worlds:4,routes,entries:['ucl','uel','uecl'],teams:counts,entry_counts:{Alpha:[3,0,0],Beta:[0,1,1],Gamma:[0,0,0],Outside:[0,1,0]}};
 X.VIZOPT.routeTeam='Alpha';const rd=X.entryRouteData(block),rh=X.vizEntryRoutes(block);
 check(!rd.error&&rh.includes('League position →')&&rh.includes('EPS league place →')&&rh.includes('75.0%')&&rh.includes('No European entry')&&rh.includes('data-entry-routes'),
  'Race Room Routes:4 specified worlds give75% Alpha UCL =50% league +25% EPS;exclusive rows and entry marginal agree');
 X.VIZOPT.routeTeam='Outside';check(X.vizEntryRoutes(block).includes('No entry through modeled rights'),
  'Race Room Routes:lower-division winner retained;unmodeled routes never called zero');
 const corrupt=structuredClone(block);corrupt.entry_routes.teams.Alpha[0][0]++;
 const marginal=structuredClone(block);marginal.teams[0].p_ucl=.5;
 check(X.entryRouteData(corrupt).error&&X.entryRouteData(marginal).error&&X.vizEntryRoutes(corrupt).includes('role="alert"')&&X.vizEntryRoutes({...block,entry_routes:undefined}).includes('no exclusive full-world'),
  'Race Room Routes:deliberate route-count/marginal faults visible;old snapshots cannot reconstruct exclusive routes');
 Object.assign(X.VIZOPT,old);
}

{
 const legacy='#section=explore&tab=Tactical+Atlas&at=Chelsea&aside=against&achart=density&acomp=English+Premier+League&against=Arsenal&abin=2-1&date=2026-10-22';
 check(Workspace.sectionFromRoute(legacy)==='clubs'&&Workspace.sectionFromRoute('#section=races&tab=English+Premier+League&view=viz&viz=density')==='clubs'&&Workspace.CLUB_SECTIONS.some(([k])=>k==='atlas'),
  'Club Atlas:legacy Explore/competition links resolve to Clubs;native club section available');
 check(X.vizGroups('league').every(([,options])=>options.every(([k])=>!['atlas','density'].includes(k))),
  'Club Atlas:duplicate competition Chart entries removed;Race Room remains registered');
 X.WORKSPACE=Workspace;X.WORKSPACE_PREFS=Workspace.emptyPreferences();globalThis.location={hash:legacy};
 X.applyHash();
 check(X.WORKSPACE_SECTION==='clubs'&&X.CLUB_SECTION==='atlas'&&X.FOCUS==='Chelsea'&&X.TEAM_PAGE,
  'Club Atlas:old link opens its exact selected club as a full club page');
 const h=new URLSearchParams(Workspace.routeHash({TAB:'English Premier League',RESULT,WORKSPACE:true,WORKSPACE_SECTION:'clubs',TEAM_PAGE:true,FOCUS:'Chelsea',CLUB_SECTION:'atlas',CLUB_SCOPE:'English Premier League',ATLAS_TEAM:'Chelsea',ATLAS_COMP:'English Premier League',ATLAS_SIDE:'against',ATLAS_CHART:'density',ATLAS_COMPARE:'Arsenal',ATLAS_BIN:'2-1',GWSEL:{},PATHSEL:{}}).slice(1));
 check(h.get('section')==='clubs'&&h.get('clubsection')==='atlas'&&h.get('team')==='Chelsea'&&h.get('aside')==='against'&&h.get('achart')==='density'&&h.get('against')==='Arsenal'&&h.get('abin')==='2-1',
  'Club Atlas:saved club route retains exact club,competition,For/Against,chart,comparison and region');
 const page=X.clubCentreHtml('Chelsea');
 check(page.includes('data-atlas-club="Chelsea"')&&page.includes('id="club-section"')&&page.includes('id="club-scope"')&&!page.includes('data-club-history='),
  'Club Atlas:club section renders the shared retained-shot root under its own club/competition header');
}

{
 const keys=['trajectory','expectation','quality'],league=RESULT.leagues[0];
 const evidenceModes={xp:'points',gx:'goals',sq:'quality',fm:'form'};
 let registrations=0,roots=0;
 for(const [kind,blocks]of[['league',RESULT.leagues],['uefa',RESULT.uefa]])for(const block of blocks)for(const [key,mode]of Object.entries(evidenceModes)){
  registrations+=Number(X.vizGroups(kind).flatMap(([,rows])=>rows).filter(([id])=>id===key).length===1);
  const markup=X.vizHtml(block,kind,key,null,null);
  roots+=Number((markup.match(/\bdata-competition-evidence\b/g)||[]).length===1&&markup.includes('data-evidence-comp="'+Workspace.esc(block.competition)+'"')&&markup.includes('data-evidence-mode="'+mode+'"')&&!markup.includes('data-performance-root')&&!markup.includes('data-chart-picker')&&!/<svg\b|<table\b/.test(markup));
 }
 const expected=4*(RESULT.leagues.length+RESULT.uefa.length);
 check(expected>0&&registrations===expected&&roots===expected,'Competition match evidence:'+expected+' exact registered lazy analysis roots retain competition/mode without duplicate inline charts; fixture numerics have independent population audits');
 check(keys.every(k=>X.vizGroups('league').some(([,rows])=>rows.some(([id])=>id===k)))
   &&keys.every(k=>X.vizGroups('uefa').every(([,rows])=>rows.every(([id])=>id!==k))),
   'Performance Studio:three registered league charts; league match-point semantics do not spread to UEFA/cups');
 check(keys.every(k=>{const html=X.vizHtml(league,'league',k,null,null);return html.includes('data-performance-root')&&html.includes('data-performance-chart="'+k+'"')&&!html.includes('data-chart-picker');}),
   'Performance Studio:each registered analysis mounts once under the existing native Chart picker');
 check(Workspace.sectionFromRoute('#section=explore&tab=Performance+Studio')==='clubs',
   'Club performance:legacy route migrates into Clubs with its analysis intact');
 const location0=globalThis.location,history0=globalThis.history;
 globalThis.history={pushState(_a,_b,hash){location.hash=hash;},replaceState(_a,_b,hash){location.hash=hash;}};
 let migrations=0;
 for(const clubs of [['Arsenal'],['Chelsea','Arsenal'],['Chelsea','Arsenal','Liverpool','Man City']]){
  const studio={clubs,competition:'all',venue:'away',chart:'quality',window:'10',side:'against',from:'2026-09-01',to:RESULT.as_of,through:'2026-10-17',detail:clubs[0]};
  globalThis.location={hash:'#section=explore&tab=Performance+Studio&date='+RESULT.source.date+'&pr='+RESULT.source.projection_sha256+'&studio='+encodeURIComponent(JSON.stringify(studio))};
  X.WORKSPACE=Workspace;X.applyHash();
  const target=clubs.length===1?X.TEAM_PAGE&&X.FOCUS===clubs[0]&&X.CLUB_SECTION==='performance':!X.TEAM_PAGE&&X.CLUB_VIEW==='compare';
  X.writeHash(false);const route=new URLSearchParams(location.hash.slice(1)),saved=JSON.parse(route.get('studio'));
  if(target&&X.WORKSPACE_SECTION==='clubs'&&X.CLUB_SCOPE==='leagues'&&X.CLUB_COMPARE_SCOPE==='leagues'&&X.CLUB_VENUE==='away'&&X.CLUB_CHART==='quality'&&JSON.stringify(X.CLUB_COMPARE)===JSON.stringify(clubs)&&JSON.stringify(saved)===JSON.stringify(studio)&&route.get('date')===RESULT.source.date&&route.get('pr')===RESULT.source.projection_sha256&&route.get('tab')!=='Performance Studio')migrations++;
 }
 check(migrations===3,'Club legacy routes:1/2/4 ordered clubs migrate to Performance/Compare; former all means Domestic leagues; exact dates/window/side/venue/source pins survive');
 globalThis.location=location0;globalThis.history=history0;
}

{
 const keys=['tmbridge','tmfates','tmstrength'],league=RESULT.leagues[0];
 check(keys.every(k=>X.vizGroups('league').some(([,rows])=>rows.some(([id])=>id===k)))
   &&keys.every(k=>['uefa','cup'].every(kind=>X.vizGroups(kind).every(([,rows])=>rows.every(([id])=>id!==k)))),
   'Time Machine:three stored-history charts registered only for league point/strength semantics');
 check(keys.every(k=>{const html=X.vizHtml(league,'league',k,null,null);return html.includes('data-time-machine')&&html.includes('data-time-chart="'+k.slice(2)+'"')&&!html.includes('data-chart-picker');}),
   'Time Machine:one lazy history mount under the shared Chart picker');
 check(Workspace.sectionFromRoute('#section=explore&tab=Time+Machine')==='explore',
   'Time Machine:Explore history workspace route remains distinct from Home');
}

// Interpretation additions: independent source accounting and deliberate faults.
{
 const saved={result:X.RESULT,viz:X.VIZSEL,options:{...X.VIZOPT}},blocks=[...RESULT.leagues,...RESULT.uefa];
 const competition='English Premier League',fixtures=[{id:'f1',competition,kind:'league',round:1,kickoff:'2026-09-01T12:00:00Z',home:'A',away:'B',result:[1,1],xg:[1,2],shots:[10,10]},{id:'f2',competition,kind:'league',round:2,kickoff:'2026-09-05T12:00:00Z',home:'A',away:'B',result:[2,0],xg:[3,1],shots:[20,5]}];
 const data={as_of:'2026-09-10',fixtures,competitions:[{competition,kind:'league',teams:['A','B']}]},state=CompetitionEvidence.stateFor(data,{competition,from:'2026-09-01',to:'2026-09-10',metric:'xgd',window:'5'},'form',competition);
 const formRefs=CompetitionEvidence.formReferences(data,state);
 check(formRefs.get('A')===.5&&formRefs.get('B')===-.5,'Form references: source (−1+2)/2 and its opposing-club identity use whole selected dates');
 const missing=structuredClone(data);missing.fixtures[0].xg[0]=null;
 check(CompetitionEvidence.formReferences(missing,state).get('A')===null,'Form reference: incomplete whole-window xG withholds the average');
 const phase=structuredClone(data);phase.competitions[0].kind='uefa';phase.fixtures=phase.fixtures.map(f=>({...f,kind:'uefa'}));phase.fixtures.push({...fixtures[0],id:'extra',kind:'uefa',round:null,xg:[100,0]});
 check(CompetitionEvidence.formReferences(phase,state).get('A')===.5,'UEFA references: unnumbered extra fixture cannot enter league-phase averages');

 let targets=0,tailOff=0;
 for(const b of blocks){X.VIZOPT.pointTarget='70';const markup=X.vizHtml(b,RESULT.uefa.includes(b)?'uefa':'league','fp');
  for(const m of markup.matchAll(/data-points-target="([^"]+)" data-target="([^"]+)" data-probability="([^"]*)"/g)){
   const name=m[1].replace(/&amp;/g,'&').replace(/&#39;/g,"'"),t=b.teams.find(t=>t.team===name),p=t?.pts;
   if(!p?.dist)continue;const mass=p.dist.reduce((a,v)=>a+v,0),want=p.dist.reduce((a,v,k)=>a+(p.offset+k>=+m[2]?v:0),0)/mass;
   targets++;if(Math.abs(+m[3]-want)>1e-10)tailOff++;
  }
 }
 check(targets>0&&tailOff===0,`Final-points targets: ${targets} displayed inclusive tails equal independent source sums`);
 check(Workspace.pointsTarget({offset:2,dist:[.2,.3,.5]},3)===.8&&Workspace.pointsTarget({offset:2,dist:[.2,.3,.5]},2)===1&&Workspace.pointsTarget({offset:2,dist:[.2,.3,.5]},5)===0,
  'Points target: inclusive boundary, below-support certainty and above-support zero');
 check([null,{offset:0,dist:[0,0]},{offset:0,dist:[-.1,1.1]},{offset:0,dist:[.1,.2]},{offset:0,dist:[null,1]}].every(p=>Workspace.pointsTarget(p,1)===null),
  'Points target: missing, zero, negative, inconsistent-mass and unknown distributions withhold');
 const equality=(want,got)=>Math.abs(want-got)<1e-10;
 check(!equality(.8,Workspace.pointsTarget({offset:2,dist:[.2,.3,.5]},4)),'Points target fault: exclusive instead of inclusive threshold fails');
 const services={useBadges:()=>false,badgeOf:()=>null,toneFill:()=>"red",shortName:t=>t,getFocus:()=>null};
 const markup=Workspace.createChartPrimitives(services).scatter([{team:'A',x:12,y:.125,tip:'A'},{team:'B',x:20,y:.1,tip:'B'}],{domain:[0,25],product:true,xlab:'volume',ylab:'quality'});
 let samples=0,curveOff=0;
 for(const m of markup.matchAll(/data-product-guide="([^"]+)"[^>]*><path d="([^"]+)"/g))for(const pair of m[2].matchAll(/[ML]([\d.]+),([\d.]+)/g)){
  const x=(+pair[1]-64)/1008*25,y=(568-(+pair[2]))/550*25;
  samples++;if(Math.abs(x*y-+m[1])>.02)curveOff++;
 }
 check(samples>0&&!curveOff,`Equal-threat contours: ${samples} rendered coordinates reconcile volume × quality to xG/match within SVG precision`);
 check(Math.abs(12*.125-1.5)<1e-12&&Math.abs(20*.1-2)<1e-12&&Math.abs(12*.1-1.5)>.1,'Quality product fault: disjoint club/population values disagree');
 check(Workspace.quantile([40,0,30,10,20],.25)===10&&Workspace.quantile([40,0,30,10,20],.5)===20&&Workspace.quantile([40,0,30,10,20],.75)===30&&Workspace.quantile([0,10,20,30],.25)===7.5,
  'League quantiles: odd/even independent ranked fixtures, linear interpolation');
 X.VIZSEL='ls';delete els.view;X.drawAllViz();let spreadCount=0,spreadOff=0;
 for(const m of mk('view').innerHTML.matchAll(/data-league-spread="([^"]+)" data-q1="([^"]+)" data-median="([^"]+)" data-q3="([^"]+)"/g)){
  const values=RESULT.ratings.teams.filter(t=>t.league===m[1]).map(t=>X.VIZOPT.lsm==='elo'?t.elo:t.att-t.def).sort((a,b)=>a-b);
  for(const [j,q] of [.25,.5,.75].entries()){const at=(values.length-1)*q,l=Math.floor(at),want=values[l]*(1-(at-l))+values[Math.ceil(at)]*(at-l);if(!equality(want,+m[j+2]))spreadOff++;}spreadCount++;
 }
 check(spreadCount===RESULT.leagues.length&&!spreadOff,'League bands: all five common-scale source populations reconcile middle half and median');
 const fx=[.8,.1,.2,.1,.9].map((w,i)=>({id:String(i),home:'A',away:'B'+i,kickoff:`2026-11-0${i+1}T12:00:00Z`,ladder:{h1:w,d:.05,a1:.95-w}}));
 const stretch=Workspace.toughestStretch([...fx].reverse(),'A','English Premier League');
 check(stretch.fixtures.map(f=>f.id).join(',')==='1,2,3'&&equality(stretch.expected,1.35),'Run-in: independent earliest minimum three-fixture window uses home 3W+D in kickoff order');
 const away=fx.map(f=>({...f,home:f.away,away:'A',ladder:{h1:f.ladder.a1,d:f.ladder.d,a1:f.ladder.h1}}));
 check(equality(Workspace.toughestStretch(away,'A','English Premier League').expected,1.35),'Run-in: mirrored away probabilities retain identical window and expected points');
 const broken=structuredClone(fx);broken[2].ladder.h1=null;
 check(Workspace.toughestStretch(broken,'A','English Premier League')===null&&Workspace.toughestStretch(fx.slice(0,2),'A','English Premier League')===null,
  'Run-in: unknown odds and fewer than three fixtures withhold the toughest-window claim');
 let windows=0,windowOff=0;
 if(GWD)for(const b of blocks){const g=(GWD.leagues||{})[b.competition]||(GWD.phases||{})[b.competition];if(!g)continue;const html=X.vizRI(b,RESULT.uefa.includes(b)?'uefa':'league',g);
  for(const m of html.matchAll(/data-ri-window="([^"]+)" data-expected="([^"]*)"/g)){
   const team=m[1].replace(/&amp;/g,'&').replace(/&#39;/g,"'"),rows=g.fixtures.filter(f=>!f.result&&(f.home===team||f.away===team)).sort((a,z)=>Workspace.fixtureInstant(a.kickoff,b.competition)-Workspace.fixtureInstant(z.kickoff,b.competition));
   if(rows.length<3)continue;const totals=Array.from({length:rows.length-2},(_,i)=>rows.slice(i,i+3).reduce((n,f)=>n+3*(f.home===team?f.ladder.h1:f.ladder.a1)+f.ladder.d,0)),want=Math.min(...totals);
   windows++;if(!equality(+m[2],want))windowOff++;
  }
 }
 check(windows>0&&!windowOff,`Run-in: ${windows} displayed windows equal independent exhaustive source minima`);
 const steps=Workspace.knockoutSteps([null,1,.6,.3,.1]);
 check(!steps.invalid&&steps.largest.index===2&&equality(steps.largest.loss,.4)&&equality(steps.steps[1].through,.5),'Knockout: absolute loss and conditional progression remain distinct');
 check(Workspace.knockoutSteps([1,1.1,.5]).invalid&&Workspace.knockoutSteps([1,.4,.5]).invalid&&!Workspace.knockoutSteps([1,0,0]).invalid,
  'Knockout: out-of-range and increasing reach ladders reject derived ratios; zero reach never divides');
 if(GWD){const b=RESULT.leagues[0],g=structuredClone(GWD.leagues[b.competition]);delete g.rating_real;X.VIZOPT.ratingReference='on';const legacy=X.vizHtml(b,'league','rt',g);
 check(!legacy.includes('data-rating-reference')&&legacy.includes('unavailable without retained real/projected flags'),'Rating reference: historical missing real/projected flags cannot turn projected worlds into a real baseline');}
 const brokenPhase=structuredClone(RESULT.uefa[0]);delete brokenPhase.teams[0].p_r16;
 X.RESULT={...RESULT,uefa:[brokenPhase]};const incomplete=X.vizHtml(brokenPhase,'uefa','ko');
 check(incomplete.includes('invalid/incomplete reach ladders')&&!new RegExp('data-ko-loss="'+brokenPhase.teams[0].team+'"').test(incomplete),
  'Knockout rendering: a missing stored stage is explicitly unavailable, never a zero reach inference');
 X.RESULT=saved.result;
 const block={competition:'Baseline fixture',teams:[{team:'A'}]},refs=new Map([['A',1.5]]);
 X.lineChart({block,id:'depthbaseline',vals:new Map([['A',[1,2,3]]]),labels:['a','b','c'],references:refs});
 check(X.LC.depthbaseline.references.get('A')===1.5,'Shared trajectory references preserve the explicitly supplied football baseline');
 X.RESULT=saved.result;X.VIZSEL=saved.viz;Object.assign(X.VIZOPT,saved.options);
}

console.log(fails ? `\n${fails} render check(s) FAILED` : "\nrender checks passed");
process.exit(fails ? 1 : 0);

} catch(error) {
 console.error(String(error.stack||error).replace(/data:text\/javascript;base64,[A-Za-z0-9+/=]+/g,"[dashboard]"));
 process.exit(1);
}
