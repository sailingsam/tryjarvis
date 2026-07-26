import {
  makeWASocket,
  useMultiFileAuthState,
  fetchLatestBaileysVersion,
  makeCacheableSignalKeyStore,
  DisconnectReason,
  type WAMessage,
  type proto,
  isJidGroup,
  jidNormalizedUser,
} from "@whiskeysockets/baileys";
import P from "pino";
import path from "node:path";
import open from "open";

import {
  initializeDatabase,
  storeMessage,
  storeChat,
  storeContact,
  type Message as DbMessage,
} from "./database.ts";

const AUTH_DIR = path.join(import.meta.dirname, "..", "auth_info");

export type WhatsAppSocket = ReturnType<typeof makeWASocket>;

// Always-current connection. Reconnect swaps `sock` here so the send path never
// holds a stale (dead) socket — the bug that made sends fail for hours after a
// laptop sleep even though Baileys had reconnected underneath.
export const conn: {
  sock: WhatsAppSocket | null;
  state: "open" | "connecting" | "close";
} = { sock: null, state: "close" };

let reconnecting = false;
let watchdogStarted = false;
const delay = (ms: number) => new Promise((r) => setTimeout(r, ms));

function scheduleReconnect(logger: P.Logger): void {
  if (reconnecting) return;
  reconnecting = true;
  logger.warn("Scheduling WhatsApp reconnect…");
  setTimeout(async () => {
    reconnecting = false;
    try {
      await startWhatsAppConnection(logger);
    } catch (e) {
      logger.error({ err: e }, "Reconnect attempt failed; will retry.");
      scheduleReconnect(logger);
    }
  }, 2000);
}

// A laptop waking from sleep can leave a zombie socket that never fires a
// 'close' event, so poll: if we're not open and not already reconnecting,
// reconnect. This resumes message capture automatically after sleep.
function startWatchdog(logger: P.Logger): void {
  if (watchdogStarted) return;
  watchdogStarted = true;
  setInterval(() => {
    if (conn.state !== "open" && !reconnecting) {
      logger.warn("Watchdog: connection not open — reconnecting.");
      scheduleReconnect(logger);
    }
  }, 30_000);
}

// Block until the connection is open (kicking a reconnect if needed), up to a
// timeout. Used before a send so a cold/stale socket recovers first.
async function ensureConnected(logger: P.Logger, timeoutMs = 25_000): Promise<boolean> {
  if (conn.state === "open" && conn.sock) return true;
  scheduleReconnect(logger);
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    await delay(500);
    if (conn.state === "open" && conn.sock) return true;
  }
  return false;
}

function parseMessageForDb(msg: WAMessage): DbMessage | null {
  if (!msg.message || !msg.key || !msg.key.remoteJid) {
    return null;
  }

  let content: string | null = null;
  const messageType = Object.keys(msg.message)[0];

  if (msg.message.conversation) {
    content = msg.message.conversation;
  } else if (msg.message.extendedTextMessage?.text) {
    content = msg.message.extendedTextMessage.text;
  } else if (msg.message.imageMessage?.caption) {
    content = `[Image] ${msg.message.imageMessage.caption}`;
  } else if (msg.message.videoMessage?.caption) {
    content = `[Video] ${msg.message.videoMessage.caption}`;
  } else if (msg.message.documentMessage?.caption) {
    content = `[Document] ${
      msg.message.documentMessage.caption ||
      msg.message.documentMessage.fileName ||
      ""
    }`;
  } else if (msg.message.audioMessage) {
    content = `[Audio]`;
  } else if (msg.message.stickerMessage) {
    content = `[Sticker]`;
  } else if (msg.message.locationMessage?.address) {
    content = `[Location] ${msg.message.locationMessage.address}`;
  } else if (msg.message.contactMessage?.displayName) {
    content = `[Contact] ${msg.message.contactMessage.displayName}`;
  } else if (msg.message.pollCreationMessage?.name) {
    content = `[Poll] ${msg.message.pollCreationMessage.name}`;
  }

  if (!content) {
    return null;
  }

  // Use WhatsApp's original message timestamp (seconds since epoch)
  let timestampSeconds: number;

  if (msg.messageTimestamp != null) {
    // Handles number, bigint, and Long-like objects
    timestampSeconds = Number(msg.messageTimestamp);
  } else {
    // Fallback only if WA didn't give us a timestamp at all
    timestampSeconds = Date.now() / 1000;
  }

  const timestamp = new Date(timestampSeconds * 1000);

  let senderJid: string | null | undefined = msg.key.participant;
  if (!msg.key.fromMe && !senderJid && !isJidGroup(msg.key.remoteJid)) {
    senderJid = msg.key.remoteJid;
  }
  if (msg.key.fromMe && !isJidGroup(msg.key.remoteJid)) {
    senderJid = null;
  }

  return {
    id: msg.key.id!,
    chat_jid: msg.key.remoteJid,
    sender: senderJid ? jidNormalizedUser(senderJid) : null,
    content: content,
    timestamp: timestamp,
    is_from_me: msg.key.fromMe ?? false,
  };
}

// WhatsApp carries the sender's display name (pushName) on messages. Store it
// as the contact's notify so chat/message listings can show real names instead
// of opaque @lid ids — the fix for "everything comes back nameless".
function capturePushName(msg: WAMessage, parsed: DbMessage): void {
  if (parsed.is_from_me || !parsed.sender || !msg.pushName) return;
  storeContact({ jid: parsed.sender, notify: msg.pushName });
}

// Pull every group the account is in, with its real subject, so groups show up
// (they were ignored before) and are searchable by name.
async function syncGroups(sock: WhatsAppSocket, logger: P.Logger): Promise<void> {
  try {
    const groups = await sock.groupFetchAllParticipating();
    const entries = Object.values(groups);
    for (const g of entries) {
      storeChat({ jid: g.id, name: g.subject });
    }
    logger.info(`Synced ${entries.length} groups with names.`);
  } catch (e) {
    logger.warn({ err: e }, "Failed to sync group metadata");
  }
}

export async function startWhatsAppConnection(
  logger: P.Logger
): Promise<WhatsAppSocket> {
  initializeDatabase();

  const { state, saveCreds } = await useMultiFileAuthState(AUTH_DIR);
  const { version, isLatest } = await fetchLatestBaileysVersion();
  logger.info(`Using WA v${version.join(".")}, isLatest: ${isLatest}`);

  const sock = makeWASocket({
    version,
    logger,
    auth: {
      creds: state.creds,
      keys: makeCacheableSignalKeyStore(state.keys, logger),
    },
    generateHighQualityLinkPreview: true,
    // Groups were being dropped by shouldIgnoreJid; keep them. And pull the
    // full history WhatsApp offers so chats/messages actually populate.
    syncFullHistory: true,
    // Group sends fetch every member's encryption session (assertSessions →
    // USync) — slow on a cold socket. Give those queries more room than the
    // 60s default; a warm daemon connection is what really makes this reliable.
    defaultQueryTimeoutMs: 90_000,
  });

  conn.sock = sock;
  conn.state = "connecting";
  startWatchdog(logger);

  sock.ev.process(async (events) => {
    if (events["connection.update"]) {
      const update = events["connection.update"];
      const { connection, lastDisconnect, qr } = update;

      if (qr) {
        logger.info(
          { qrCodeData: qr },
          "QR Code Received. Copy the qrCodeData string and use a QR code generator (e.g., online website) to display and scan it with your WhatsApp app."
        );
        // for now we roughly open the QR code in a browser
        await open(`https://quickchart.io/qr?text=${encodeURIComponent(qr)}`);
      }

      if (connection === "close") {
        conn.state = "close";
        const statusCode = (lastDisconnect?.error as any)?.output?.statusCode;
        logger.warn(
          `Connection closed. Reason: ${
            DisconnectReason[statusCode as number] || "Unknown"
          }`,
          lastDisconnect?.error
        );
        if (statusCode !== DisconnectReason.loggedOut) {
          scheduleReconnect(logger);
        } else {
          logger.error(
            "Connection closed: Logged Out. Please delete auth_info and restart."
          );
          process.exit(1);
        }
      } else if (connection === "open") {
        conn.state = "open";
        logger.info(`Connection opened. WA user: ${sock.user?.name}`);
        syncGroups(sock, logger);
      }
    }

    if (events["creds.update"]) {
      await saveCreds();
      logger.info("Credentials saved.");
    }

    if (events["messaging-history.set"]) {
      const { chats, contacts, messages, isLatest, progress, syncType } =
        events["messaging-history.set"];
      if (contacts.length > 0) {
        logger.info(`Storing ${contacts.length} contacts from history sync.`);
        contacts.forEach((c) =>
          storeContact({
            jid: c.id,
            name: c.name ?? null,
            notify: c.notify ?? null,
            phoneNumber: (c as any).phoneNumber ?? null,
          })
        );
        logger.info(`Stored ${contacts.length} contacts from history sync.`);
      }

      logger.info(`Storing ${chats.length} chats from history sync.`);
      chats.forEach((chat) =>
        storeChat({
          jid: chat.id,
          name: chat.name,
          last_message_time: chat.conversationTimestamp
            ? new Date(Number(chat.conversationTimestamp) * 1000)
            : undefined,
        })
      );

      let storedCount = 0;
      messages.forEach((msg) => {
        const parsed = parseMessageForDb(msg);
        if (parsed) {
          capturePushName(msg, parsed);
          storeMessage(parsed);
          storedCount++;
        }
      });
      logger.info(`Stored ${storedCount} messages from history sync.`);
    }

    if (events["messages.upsert"]) {
      const { messages, type } = events["messages.upsert"];
      logger.info(
        { type, count: messages.length },
        "Received messages.upsert event"
      );

      if (type === "notify" || type === "append") {
        for (const msg of messages) {
          const parsed = parseMessageForDb(msg);
          if (parsed) {
            capturePushName(msg, parsed);
            logger.info(
              {
                msgId: parsed.id,
                chatId: parsed.chat_jid,
                fromMe: parsed.is_from_me,
                sender: parsed.sender,
              },
              `Storing message: ${parsed.content.substring(0, 50)}...`
            );
            storeMessage(parsed);
          } else {
            logger.warn(
              { msgId: msg.key?.id, chatId: msg.key?.remoteJid },
              "Skipped storing message (parsing failed or unsupported type)"
            );
          }
        }
      }
    }

    if (events["chats.update"]) {
      logger.info(
        { count: events["chats.update"].length },
        "Received chats.update event"
      );
      for (const chatUpdate of events["chats.update"]) {
        storeChat({
          jid: chatUpdate.id!,
          name: chatUpdate.name,
          last_message_time: chatUpdate.conversationTimestamp
            ? new Date(Number(chatUpdate.conversationTimestamp) * 1000)
            : undefined,
        });
      }
    }
  });

  return sock;
}

function isConnectionClosed(error: any): boolean {
  const msg = String(error?.message || "").toLowerCase();
  return msg.includes("connection closed") || error?.output?.statusCode === 428;
}

export async function sendWhatsAppMessage(
  logger: P.Logger,
  recipientJid: string,
  text: string
): Promise<proto.WebMessageInfo | void> {
  if (!recipientJid || !text) {
    logger.error("Cannot send message: missing recipient or text.");
    return;
  }

  // Recover from a cold/stale/slept connection before sending.
  if (!(await ensureConnected(logger))) {
    logger.error("Cannot send message: not connected after reconnect attempt.");
    return;
  }

  // Groups (@g.us) must NOT be run through jidNormalizedUser (that's for user
  // JIDs); pass group JIDs through untouched.
  const targetJid = isJidGroup(recipientJid)
    ? recipientJid
    : jidNormalizedUser(recipientJid);

  for (let attempt = 1; attempt <= 2; attempt++) {
    try {
      logger.info(`Sending message to ${targetJid}: ${text.substring(0, 50)}...`);
      const result = await conn.sock!.sendMessage(targetJid, { text });
      logger.info({ msgId: result?.key.id }, "Message sent successfully");
      return result;
    } catch (error) {
      logger.error({ err: error, recipientJid: targetJid, attempt }, "Failed to send message");
      // Dead socket (e.g. after sleep): force a reconnect, wait, and retry once.
      if (isConnectionClosed(error) && attempt === 1) {
        conn.state = "close";
        if (!(await ensureConnected(logger))) return;
        continue;
      }
      return;
    }
  }
}
