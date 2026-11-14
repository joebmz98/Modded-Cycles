/* Song mode, stage 1 (notes/74): a song table sent over SysEx, played by writing the pattern chain from the UI task.
 *
 * Two entry points, both reached through hooks written by tools/gen_song.py:
 *   - song_sysex(msg, len, port): our entry in the OS's SysEx router (0x40081300, table 0x40148d08, product SONG_P).
 *     Runs in the MIDI task. It only copies the song, records requests and answers; it never touches the sequencer.
 *   - song_tick(): the UI task's 30 Hz tick (hook at 0x400081ea, which called 0x400d0b12: we call it and return its
 *     result). Runs the song: counts the pattern loops, queues the next row's pattern through 0x40055cd6 (what an
 *     incoming Program Change calls) one loop early, and applies each row's mutes and tempo as the row begins.
 *
 * Messages: F0 00 20 3C SONG_P 00 cmd <body, 7-bit packed> F7; replies F0 00 20 3C SONG_P 00 (cmd | 0x40) <status,
 * body, 7-bit packed> F7, sent on USB only (port 2). Protocol: docs/arranger/SONG-PROTOCOL.md.
 *
 * Built with -ffunction-sections; song.ld places each function in a freed sprite mask. OS calls are declared as
 * returning integers so that d0 is read whatever the compiler's ABI for pointers. */

typedef unsigned char u8;
typedef unsigned short u16;
typedef unsigned long u32;

#define SONG_P 0x0e
#define MAX_ROWS 128
#define MAX_LANES 8
#define NO_VALUE 0xff                           /* a lane with no value in a row */
#define ROW_BYTES 6
#define MAGIC 0x534f4e47UL                      /* "SONG": the variables above the BSS are not cleared at start-up */

/* OS 1.13 (notes/74) */
#define USB_SEND(n, p)      ((void (*)(u32, const u8 *))0x40003396)((n), (p))
#define SET_CHAIN(p, n)     ((void (*)(const u32 *, u32))0x40055cd6)((p), (n))
#define UI_APP()            ((u32 (*)(void))0x400cf866)()
#define PROJECT(app)        ((u32 (*)(u32))0x4000eb90)(app)
#define SET_MUTE(pr, t, m)  ((void (*)(u32, u32, u32, u32))0x4001381c)((pr), (t), (m), 0)
#define SET_TEMPO(pr, t)    ((void (*)(u32, u32))0x4000c846)((pr), (t))
#define TICK_NEXT()         ((u32 (*)(void))0x400d0b12)()
#define SET_CC(tg, cc, v)   ((void (*)(u32, u32, u32, u32, u32))0x40082cda)((tg), (cc), (v), 0, 0)   /* what a received CC calls */
#define SEQ_PLAYING         (*(volatile u32 *)0x40a7883c)
#define SEQ_STEP            (*(volatile u32 *)0x40a78840)
#define PAT_BANK 0x406fa040UL
#define PAT_SIZE 30710UL
#define KIT_BANK 0x409c9c80UL
#define KIT_SIZE 7094UL

enum { C_INFO, C_WRITE, C_READ, C_PLAY, C_STOP, C_STATUS, C_MODE, C_LANE, C_COUNT };
enum { S_OK, S_BUSY, S_LENGTH, S_ROWS, S_PATTERN, S_NOSONG, S_UNKNOWN = 0x7f };

/* the song, as sent: ver, name_len, name[16], n, loop_on, loop_start, loop_end, rows[n][6] */
struct song {
    u8 name_len;
    u8 name[16];
    u8 n, loop_on, loop_start, loop_end;
    u8 rows[MAX_ROWS][ROW_BYTES];               /* pattern 0..95, repeats 1..255, mute mask, flags, tempo hi, lo */
};

void song_sysex(const u8 *msg, u32 len, u32 port);

/* our entry in the SysEx router's table (0x40148d08[SONG_P]): id, sub-id, handlers, first and last command, base */
struct route { u8 id, sub, pad[2]; void (*const *table)(const u8 *, u32, u32); u32 min, max, base; };
__attribute__((section(".rodata.route"))) void (*const song_handlers[C_COUNT])(const u8 *, u32, u32) = {
    song_sysex, song_sysex, song_sysex, song_sysex, song_sysex, song_sysex, song_sysex, song_sysex,
};
__attribute__((section(".rodata.route"))) const struct route song_route = {
    SONG_P, 0x00, {0, 0}, song_handlers, 0, C_COUNT - 1, 0,
};

u32 magic;
struct song song;
volatile u8 busy;                               /* the MIDI task is replacing the song */
volatile u8 mode;                               /* song mode on: the song drives the patterns while the sequencer plays */
volatile u8 req_play, req_row, req_stop;        /* requests from the MIDI task to the UI task */
u8 running, row, rep, queued, ended;
u32 last_step;
u32 pair[2];
u8 buf[1024];
/* CC lanes (protocol v2): per lane its target (track 0..5, 6 = the FX channel), its CC and, per row, a start and an end
   value (NO_VALUE: the lane does nothing in that row) */
struct lane { u8 target, cc, v[MAX_ROWS][2]; };
struct lane lanes[MAX_LANES];
u8 nlanes;
u8 sent[MAX_LANES];                             /* last value sent per lane, NO_VALUE after a row begins */
u8 plen[96];                                    /* steps per loop of each pattern, learnt at its wraps (0: not yet) */                                   /* decoded body in, then the reply out */

/* ---- 7-bit packing (Elektron's: a byte of top bits, first byte in bit 6, then up to 7 bytes) ---- */
__attribute__((noinline, section(".text.unpack"))) static u32 unpack(const u8 *in, u32 n, u8 *out, u32 room)
{
    u32 o = 0;
    while (n) {
        u8 top = *in++;
        u32 k;
        n--;
        for (k = 0; k < 7 && n; k++, n--) {
            if (o >= room)
                return 0xffffffffUL;
            out[o++] = *in++ | (((top >> (6 - k)) & 1) << 7);
        }
    }
    return o;
}

__attribute__((noinline, section(".text.reply"))) static void reply(u32 port, u8 cmd, const u8 *body, u32 n)
{
    static u8 msg[7 + 1200];
    u32 o = 7, i = 0;
    if (port != 2)                              /* answers go back over USB only */
        return;
    msg[0] = 0xf0; msg[1] = 0x00; msg[2] = 0x20; msg[3] = 0x3c; msg[4] = SONG_P; msg[5] = 0x00; msg[6] = cmd | 0x40;
    while (i < n) {
        u32 h = o++, k;
        msg[h] = 0;
        for (k = 0; k < 7 && i < n; k++, i++) {
            msg[h] |= (body[i] >> 7) << (6 - k);
            msg[o++] = body[i] & 0x7f;
        }
    }
    msg[o++] = 0xf7;
    USB_SEND(o, msg);
}

__attribute__((noinline, section(".text.init"))) static void init(void)
{
    u32 k;
    if (magic == MAGIC)
        return;
    busy = 0; mode = 0; req_play = 0; req_stop = 0; running = 0; ended = 0;
    song.n = 0;
    nlanes = 0;
    for (k = 0; k < 96; k++)
        plen[k] = 0;
    magic = MAGIC;
}

/* the song body: checks it completely before replacing the current song */
__attribute__((noinline, section(".text.store"))) static u8 store(const u8 *b, u32 n)
{
    u32 i, rows, need;
    const u8 *r;
    if (n < 6 || b[0] != 1 || b[1] > 16)
        return S_LENGTH;
    rows = b[2 + b[1]];
    if (rows > MAX_ROWS)
        return S_ROWS;
    need = 6 + b[1] + rows * ROW_BYTES;
    if (n < need)
        return S_LENGTH;
    r = b + 6 + b[1];
    for (i = 0; i < rows; i++)
        if (r[i * ROW_BYTES] > 95 || r[i * ROW_BYTES + 1] == 0)
            return S_PATTERN;
    busy = 1;
    running = 0;
    song.name_len = b[1];
    for (i = 0; i < b[1]; i++)
        song.name[i] = b[2 + i];
    song.n = rows;
    nlanes = 0;
    song.loop_on = b[3 + b[1]];
    song.loop_start = b[4 + b[1]];
    song.loop_end = b[5 + b[1]];
    if (song.loop_start >= rows || song.loop_end >= rows || song.loop_end < song.loop_start)
        song.loop_on = 0;
    for (i = 0; i < rows * ROW_BYTES; i++)
        song.rows[0][i] = r[i];
    mode = 1;
    busy = 0;
    return S_OK;
}

__attribute__((noinline, section(".text.load"))) static u32 load(u8 *b)
{
    u32 i, o = 0;
    b[o++] = S_OK;
    b[o++] = 1;
    b[o++] = song.name_len;
    for (i = 0; i < song.name_len; i++)
        b[o++] = song.name[i];
    b[o++] = song.n;
    b[o++] = song.loop_on;
    b[o++] = song.loop_start;
    b[o++] = song.loop_end;
    for (i = 0; i < (u32)song.n * ROW_BYTES; i++)
        b[o++] = song.rows[0][i];
    return o;
}

/* a lane: index, target, cc, rows, then rows x (start, end) */
__attribute__((noinline, section(".text.store_lane"))) static u8 store_lane(const u8 *b, u32 n)
{
    u32 i, rows;
    struct lane *l;
    if (n < 4 || b[0] >= MAX_LANES || b[1] > 6 || b[2] > 127)
        return S_LENGTH;
    rows = b[3];
    if (rows > MAX_ROWS || n < 4 + rows * 2)
        return S_LENGTH;
    busy = 1;
    l = &lanes[b[0]];
    l->target = b[1];
    l->cc = b[2];
    for (i = 0; i < MAX_ROWS; i++) {
        l->v[i][0] = i < rows ? b[4 + 2 * i] : NO_VALUE;
        l->v[i][1] = i < rows ? b[5 + 2 * i] : NO_VALUE;
    }
    if (b[0] >= nlanes)
        nlanes = b[0] + 1;
    sent[b[0]] = NO_VALUE;
    busy = 0;
    return S_OK;
}

/* INFO, STATUS and READ answer with data */
__attribute__((noinline, section(".text.answer"))) static void answer(u8 cmd, u32 port)
{
    u32 n = 1;
    buf[0] = S_OK;
    if (cmd == C_INFO) {
        buf[1] = 2; buf[2] = MAX_ROWS; buf[3] = MAX_LANES;
        n = 4;
    } else if (cmd == C_STATUS) {
        buf[1] = running; buf[2] = row; buf[3] = rep; buf[4] = mode;
        n = 5;
    } else if (!song.n)
        buf[0] = S_NOSONG;
    else
        n = load(buf);
    reply(port, cmd, buf, n);
}

/* WRITE, PLAY, STOP and MODE change something and answer with a status */
__attribute__((noinline, section(".text.act"))) static u8 act(u8 cmd, u32 n)
{
    switch (cmd) {
    case C_WRITE:
        return n == 0xffffffffUL ? S_LENGTH : store(buf, n);
    case C_PLAY:
        if (!song.n)
            return S_NOSONG;
        req_row = (n >= 1 && buf[0] < song.n) ? buf[0] : 0;
        mode = 1;
        req_play = 1;
        return S_OK;
    case C_STOP:
        req_stop = 1;
        return S_OK;
    case C_LANE:
        return n == 0xffffffffUL ? S_LENGTH : store_lane(buf, n);
    case C_MODE:
        mode = n >= 1 && buf[0];
        if (!mode)
            req_stop = 1;
        return S_OK;
    }
    return S_UNKNOWN;
}

__attribute__((section(".text.song_sysex"))) void song_sysex(const u8 *msg, u32 len, u32 port)
{
    u32 n;
    u8 cmd;
    init();
    if (len < 8 || msg[5] != 0x00)
        return;
    cmd = msg[6];
    n = unpack(msg + 7, len - 8, buf, sizeof buf);
    if (cmd == C_INFO || cmd == C_STATUS || cmd == C_READ) {
        answer(cmd, port);
        return;
    }
    buf[0] = act(cmd, n);
    reply(port, cmd, buf, 1);
}

/* ---- the engine, in the UI task ---- */
__attribute__((noinline, section(".text.next_row"))) static int next_row(u32 r)
{
    if (song.loop_on && r == song.loop_end)
        return song.loop_start;
    return r + 1 < song.n ? (int)(r + 1) : -1;
}

__attribute__((noinline, section(".text.queue"))) static void queue(u32 r)
{
    u32 p = song.rows[r][0];
    pair[0] = PAT_BANK + p * PAT_SIZE;
    pair[1] = KIT_BANK + p * KIT_SIZE;
    SET_CHAIN(pair, 1);
}

/* a row begins: its mutes and tempo; and, if it plays once, the next pattern straight away */
__attribute__((noinline, section(".text.enter_row"))) static void enter_row(u32 r)
{
    const u8 *w = song.rows[r];
    u32 pr = PROJECT(UI_APP()), t;
    row = r;
    rep = 0;
    queued = 0;
    for (t = 0; t < MAX_LANES; t++)
        sent[t] = NO_VALUE;
    for (t = 0; t < 6; t++)
        SET_MUTE(pr, t, (w[2] >> t) & 1);
    if (w[3] & 1)
        SET_TEMPO(pr, ((u32)w[4] << 8) | w[5]);
}

/* the lanes of the playing row, ramped from start to end across all its loops */
__attribute__((noinline, section(".text.apply_lanes"))) static void apply_lanes(u32 step)
{
    u32 i, len = plen[song.rows[row][0]], reps = song.rows[row][1], pos, total, v;
    const u8 *w;
    if (ended)
        return;
    if (!len)
        len = 16;                               /* not looped yet: 16 steps until its first wrap is seen */
    if (step >= len)
        step = len - 1;
    total = reps * len - 1;
    pos = rep * len + step;
    if (pos > total)
        pos = total;
    for (i = 0; i < nlanes; i++) {
        w = lanes[i].v[row];
        if (w[0] == NO_VALUE)
            continue;
        v = total ? (w[0] * (total - pos) + w[1] * pos) / total : w[0];
        if (v != sent[i]) {
            SET_CC(lanes[i].target, lanes[i].cc, v);
            sent[i] = v;
        }
    }
}

/* the row's last loop has begun: queue what follows it, once */
__attribute__((noinline, section(".text.queue_next"))) static void queue_next(void)
{
    int nx;
    if (ended || queued || rep + 1 < song.rows[row][1])
        return;
    nx = next_row(row);
    queue(nx < 0 ? row : (u32)nx);
    queued = 1;
}

/* requests from the MIDI task; 1 if one was handled this tick */
__attribute__((noinline, section(".text.requests"))) static int requests(void)
{
    if (req_stop) {
        req_stop = 0;
        req_play = 0;
        running = 0;
        mode = 0;
        return 1;
    }
    if (req_play) {                              /* stopped: the row's pattern loads at once; playing: at the wrap */
        req_play = 0;
        running = 0;
        ended = 0;
        queue(req_row);
        row = req_row;
        return 1;
    }
    return 0;
}

__attribute__((section(".text.song_tick_c"))) void song_tick_c(void)
{
    u32 step;
    int nx;
    init();
    if (busy || !song.n)
        return;
    if (requests())
        return;
    if (!mode)
        return;
    step = SEQ_STEP;
    if (!SEQ_PLAYING) {
        running = 0;
        last_step = 0;
        return;
    }
    if (!running) {                              /* the sequencer just started: the song starts at the armed row */
        running = 1;
        ended = 0;
        enter_row(row);
        last_step = step;
    } else if (step < last_step && !ended) {     /* the pattern looped */
        plen[song.rows[row][0]] = last_step + 1 > 255 ? 255 : last_step + 1;
        if (++rep >= song.rows[row][1]) {
            nx = next_row(row);
            if (nx < 0)
                ended = 1;                       /* the last row keeps looping */
            else
                enter_row(nx);
        }
    }
    last_step = step;
    queue_next();
    apply_lanes(step);
}

__attribute__((section(".text.song_tick"))) u32 song_tick(void)
{
    song_tick_c();
    return TICK_NEXT();
}
