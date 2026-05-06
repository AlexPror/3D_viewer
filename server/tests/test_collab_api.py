import importlib
import os
import tempfile
import unittest
from io import BytesIO
from pathlib import Path

from fastapi.testclient import TestClient


class CollabApiTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(cls._tmpdir.name) / "test-collab.sqlite3"
        os.environ["COLLAB_DB_PATH"] = str(db_path)
        os.environ["COLLAB_AUTH_SECRET"] = "test-secret"
        os.environ["COLLAB_TOKEN_TTL_SECONDS"] = "3600"

        import main as main_module  # type: ignore

        cls.main = importlib.reload(main_module)
        cls.client = TestClient(cls.main.app)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.client.close()
        cls._tmpdir.cleanup()

    def register_and_login(self, email: str, display_name: str = "User") -> str:
        reg = self.client.post(
            "/api/auth/register",
            json={"email": email, "password": "Test12345", "display_name": display_name},
        )
        self.assertEqual(reg.status_code, 200, reg.text)
        reg_data = reg.json()
        self.assertTrue(reg_data.get("ok"))
        token = reg_data.get("token")
        self.assertTrue(token)

        login = self.client.post(
            "/api/auth/login",
            json={"email": email, "password": "Test12345"},
        )
        self.assertEqual(login.status_code, 200, login.text)
        self.assertTrue(login.json().get("token"))
        return token

    def test_auth_and_me(self) -> None:
        token = self.register_and_login("auth1@example.com", "Auth One")
        me = self.client.get("/api/me", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(me.status_code, 200, me.text)
        body = me.json()
        self.assertTrue(body.get("ok"))
        self.assertEqual(body["user"]["email"], "auth1@example.com")

    def test_project_channel_and_messages_flow(self) -> None:
        token = self.register_and_login("flow1@example.com", "Flow One")
        headers = {"Authorization": f"Bearer {token}"}

        create_project = self.client.post("/api/projects", json={"name": "Project A"}, headers=headers)
        self.assertEqual(create_project.status_code, 200, create_project.text)
        project = create_project.json()["project"]
        project_id = project["id"]

        list_projects = self.client.get("/api/projects", headers=headers)
        self.assertEqual(list_projects.status_code, 200, list_projects.text)
        self.assertGreaterEqual(len(list_projects.json().get("projects", [])), 1)

        channels = self.client.get(f"/api/projects/{project_id}/channels", headers=headers)
        self.assertEqual(channels.status_code, 200, channels.text)
        ch_list = channels.json().get("channels", [])
        self.assertGreaterEqual(len(ch_list), 1)
        general_id = ch_list[0]["id"]

        created_channel = self.client.post(
            f"/api/projects/{project_id}/channels",
            json={"name": "Монтаж", "kind": "module"},
            headers=headers,
        )
        self.assertEqual(created_channel.status_code, 200, created_channel.text)
        custom_channel_id = created_channel.json()["channel"]["id"]

        msg1 = self.client.post(
            f"/api/projects/{project_id}/channels/{general_id}/messages",
            json={"body": "Сообщение 1"},
            headers=headers,
        )
        self.assertEqual(msg1.status_code, 200, msg1.text)

        msg2 = self.client.post(
            f"/api/projects/{project_id}/channels/{custom_channel_id}/messages",
            json={"body": "Сообщение 2"},
            headers=headers,
        )
        self.assertEqual(msg2.status_code, 200, msg2.text)

        read_general = self.client.get(
            f"/api/projects/{project_id}/channels/{general_id}/messages",
            headers=headers,
        )
        self.assertEqual(read_general.status_code, 200, read_general.text)
        msgs = read_general.json().get("messages", [])
        self.assertGreaterEqual(len(msgs), 1)
        self.assertEqual(msgs[-1]["body"], "Сообщение 1")

    def test_member_roles_block_viewer_write(self) -> None:
        owner_token = self.register_and_login("owner@example.com", "Owner")
        owner_headers = {"Authorization": f"Bearer {owner_token}"}
        viewer_token = self.register_and_login("viewer@example.com", "Viewer")
        viewer_headers = {"Authorization": f"Bearer {viewer_token}"}

        project_resp = self.client.post("/api/projects", json={"name": "Role Project"}, headers=owner_headers)
        self.assertEqual(project_resp.status_code, 200, project_resp.text)
        project_id = project_resp.json()["project"]["id"]
        channels = self.client.get(f"/api/projects/{project_id}/channels", headers=owner_headers).json()["channels"]
        general_id = channels[0]["id"]

        add_member = self.client.post(
            f"/api/projects/{project_id}/members",
            json={"email": "viewer@example.com", "role": "viewer"},
            headers=owner_headers,
        )
        self.assertEqual(add_member.status_code, 200, add_member.text)

        viewer_post = self.client.post(
            f"/api/projects/{project_id}/channels/{general_id}/messages",
            json={"body": "try write"},
            headers=viewer_headers,
        )
        self.assertEqual(viewer_post.status_code, 403, viewer_post.text)

        viewer_channels = self.client.get(
            f"/api/projects/{project_id}/channels",
            headers=viewer_headers,
        )
        self.assertEqual(viewer_channels.status_code, 200, viewer_channels.text)

    def test_attachment_upload_and_bind_to_message(self) -> None:
        token = self.register_and_login("attach1@example.com", "Attach One")
        headers = {"Authorization": f"Bearer {token}"}

        project_resp = self.client.post("/api/projects", json={"name": "Attach Project"}, headers=headers)
        self.assertEqual(project_resp.status_code, 200, project_resp.text)
        project_id = project_resp.json()["project"]["id"]
        channels = self.client.get(f"/api/projects/{project_id}/channels", headers=headers).json()["channels"]
        channel_id = channels[0]["id"]

        png_bytes = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
            b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\x0cIDATx\x9cc\xf8\xff\xff?"
            b"\x00\x05\xfe\x02\xfeA\xb6\x8f\x1d\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        upload = self.client.post(
            f"/api/projects/{project_id}/attachments/upload",
            headers=headers,
            files={"file": ("shot.png", BytesIO(png_bytes), "image/png")},
            data={"source": "pdf", "context_json": '{"page": 3}'},
        )
        self.assertEqual(upload.status_code, 200, upload.text)
        attachment = upload.json()["attachment"]
        attachment_id = attachment["id"]
        self.assertTrue(attachment_id)

        msg = self.client.post(
            f"/api/projects/{project_id}/channels/{channel_id}/messages",
            headers=headers,
            json={"body": "msg with attachment", "attachmentIds": [attachment_id]},
        )
        self.assertEqual(msg.status_code, 200, msg.text)
        m = msg.json()["message"]
        self.assertEqual(m["body"], "msg with attachment")
        self.assertEqual(len(m.get("attachments", [])), 1)
        self.assertEqual(m["attachments"][0]["id"], attachment_id)

        dl = self.client.get(
            f"/api/projects/{project_id}/attachments/{attachment_id}",
            headers=headers,
        )
        self.assertEqual(dl.status_code, 200, dl.text)
        self.assertEqual(dl.headers.get("content-type"), "image/png")

    def test_mark_read_endpoint(self) -> None:
        token = self.register_and_login("read1@example.com", "Read One")
        headers = {"Authorization": f"Bearer {token}"}

        project_resp = self.client.post("/api/projects", json={"name": "Read Project"}, headers=headers)
        self.assertEqual(project_resp.status_code, 200, project_resp.text)
        project_id = project_resp.json()["project"]["id"]
        channels = self.client.get(f"/api/projects/{project_id}/channels", headers=headers).json()["channels"]
        channel_id = channels[0]["id"]
        msg = self.client.post(
            f"/api/projects/{project_id}/channels/{channel_id}/messages",
            headers=headers,
            json={"body": "msg for read"},
        ).json()["message"]

        mark = self.client.post(
            f"/api/projects/{project_id}/channels/{channel_id}/read",
            headers=headers,
            json={"lastReadMsgId": msg["id"]},
        )
        self.assertEqual(mark.status_code, 200, mark.text)
        self.assertTrue(mark.json().get("ok"))
        self.assertEqual(mark.json()["readState"]["last_read_msg_id"], msg["id"])

    def test_websocket_receives_message_event(self) -> None:
        token = self.register_and_login("ws1@example.com", "Ws One")
        headers = {"Authorization": f"Bearer {token}"}
        project_resp = self.client.post("/api/projects", json={"name": "Ws Project"}, headers=headers)
        self.assertEqual(project_resp.status_code, 200, project_resp.text)
        project_id = project_resp.json()["project"]["id"]
        channels = self.client.get(f"/api/projects/{project_id}/channels", headers=headers).json()["channels"]
        channel_id = channels[0]["id"]

        with self.client.websocket_connect(f"/api/projects/{project_id}/ws?token={token}") as ws:
            connected_evt = ws.receive_json()
            self.assertEqual(connected_evt.get("type"), "ws.connected")
            create_msg = self.client.post(
                f"/api/projects/{project_id}/channels/{channel_id}/messages",
                headers=headers,
                json={"body": "hello ws"},
            )
            self.assertEqual(create_msg.status_code, 200, create_msg.text)
            evt = ws.receive_json()
            self.assertEqual(evt.get("type"), "chat.message.created")
            self.assertEqual(evt.get("channelId"), channel_id)


if __name__ == "__main__":
    unittest.main()
