# Privacy Policy

We are committed to protecting your privacy and ensuring a secure experience when using the **GLC Bot** (the "Bot") on Discord. This Privacy Policy explains what information we collect, how it is used, and how it is protected.

By adding or interacting with the Bot, you agree to the practices described in this Privacy Policy.

---

## 1. Information We Collect
To function properly and provide its services, the Bot may access and process certain information from Discord. This data is split into two categories:

### A. Data Automatically Accessed (via Discord APIs)
* **Guild (Server) Information:** Server IDs, server names, and channel names to configure permissions and route/dispatch briefings.
* **User Information:** Discord User IDs, usernames, and display names to identify who executes commands or receives notifications.
* **Message Metadata:** Message IDs, timestamps, and channel IDs.
* **Message Content:** If the Bot has the `Message Content Intent` enabled, it reads message text solely to detect commands and process requests (e.g., executing channel instructions).

### B. Data You Provide
* Configuration settings or parameters you pass when invoking the Bot's commands.

---

## 2. How We Use the Information
The collected information is used strictly to operate, maintain, and improve the Bot's functionality:
* To process and respond to commands initiated by users.
* To route briefings or notifications to the specified Discord channels.
* To debug technical issues and analyze error logs to maintain stability.

---

## 3. Data Retention and Storage
We respect your data privacy and keep data retention to the absolute minimum:
* **No Persistent Log of Messages:** The Bot does not store message contents or user chat history persistently. Message contents are processed in memory and immediately discarded after command execution.
* **Configuration Storage:** Basic configuration details (such as channel mappings or server preferences) may be stored in local databases or environment files necessary to keep the Bot running.
* **Temporary Memory Cache:** Certain data like active channel IDs may be cached in transient memory to optimize performance and respect Discord rate limits.

---

## 4. Information Sharing and Disclosure
We do not sell, trade, or otherwise transfer your data to outside parties. Your data is only shared in the following situations:
* **Discord API:** To communicate with Discord servers, data is transmitted through Discord's official API endpoints.
* **Legal Requirements:** If required by law, we may disclose information to comply with legal obligations or protect the rights and safety of users.

---

## 5. Security of Your Data
We implement appropriate technical and organizational measures to secure your data from unauthorized access, loss, or alteration. Access to bot hosting environments, tokens, and database configurations is restricted only to authorized developers and administrators.

---

## 6. User Rights and Data Deletion
You have control over your data:
* **Removing the Bot:** You can revoke the Bot's access at any time by kicking or banning the Bot from your Discord server.
* **Request Data Deletion:** If you wish to request deletion of any cached configuration data related to your user or server, please open an issue in this repository or contact the repository administrator.

---

## 7. Changes to this Privacy Policy
We may update this Privacy Policy from time to time. Any changes will be committed directly to this repository. Your continued use of the Bot after updates are made constitutes acceptance of the revised Privacy Policy.

---

## 8. Contact Information
If you have any questions or concerns regarding this Privacy Policy or your data, please reach out by opening an issue in this repository.
