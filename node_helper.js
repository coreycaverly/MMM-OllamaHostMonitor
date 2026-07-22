/* MagicMirror² Module: MMM-OllamaHostMonitor
 *
 * node_helper: subscribes to the Mac Studio metrics on your MQTT broker and
 * forwards each message to the front-end module. Retained messages mean the
 * UI populates the moment MagicMirror starts.
 */
const NodeHelper = require("node_helper");
const mqtt = require("mqtt");

module.exports = NodeHelper.create({
  start() {
    this.clients = {}; // keyed by broker url so multiple instances share a socket
  },

  // Called by MagicMirror on shutdown — close the MQTT connections cleanly.
  stop() {
    for (const key of Object.keys(this.clients)) {
      try {
        this.clients[key].end(true);
      } catch (e) {
        // ignore
      }
    }
    this.clients = {};
  },

  socketNotificationReceived(notification, config) {
    if (notification === "MSM_CONFIG") {
      this.connect(config);
    }
  },

  connect(config) {
    const port = config.mqttPort || 1883;
    const url = `mqtt://${config.mqttServer}:${port}`;
    const prefix = (config.topicPrefix || "ollama-host/metrics").replace(/\/+$/, "");
    const clientKey = `${url}|${prefix}`;
    if (this.clients[clientKey]) {
      return; // already connected for this broker+prefix
    }

    const options = { reconnectPeriod: 5000 };
    if (config.mqttUser) {
      options.username = config.mqttUser;
      options.password = config.mqttPassword;
    }

    const client = mqtt.connect(url, options);
    this.clients[clientKey] = client;

    client.on("connect", () => {
      console.log(`[MMM-OllamaHostMonitor] connected to ${url}, subscribing ${prefix}/#`);
      client.subscribe(`${prefix}/#`, (err) => {
        if (err) console.error("[MMM-OllamaHostMonitor] subscribe error:", err.message);
      });
    });

    client.on("message", (topic, message) => {
      const key = topic.slice(prefix.length + 1); // system | ollama | hermes | availability
      let data;
      if (key === "availability") {
        data = message.toString();
      } else {
        try {
          data = JSON.parse(message.toString());
        } catch (e) {
          return; // ignore malformed payloads
        }
      }
      this.sendSocketNotification("MSM_DATA", { key, data });
    });

    client.on("error", (e) => console.error("[MMM-OllamaHostMonitor] mqtt error:", e.message));
    client.on("reconnect", () => console.log("[MMM-OllamaHostMonitor] reconnecting to", url));
  }
});
