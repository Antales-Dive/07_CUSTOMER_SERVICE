import unittest
from pathlib import Path


HTML_PATH = Path(__file__).resolve().parents[1] / "static" / "index.html"


def function_body(source, name):
    marker = f"function {name}"
    start = source.index(marker)
    opening_brace = source.index("{", start)
    depth = 0
    for index in range(opening_brace, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[opening_brace + 1:index]
    raise ValueError(f"Unbalanced braces in function {name}")


class CompanionUIStructureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = HTML_PATH.read_text(encoding="utf-8")

    def test_identity_and_welcome_copy(self):
        required_copy = (
            "<title>有话说</title>",
            "今天过得怎么样？",
            "不用想好怎么说，想到哪儿说到哪儿。",
            "慢慢说，我在听。",
            "最近聊过",
            "重新聊聊",
        )
        for copy in required_copy:
            with self.subTest(copy=copy):
                self.assertIn(copy, self.html)

    def test_all_conversation_modes_are_present(self):
        mode_labels = (
            "我只想吐槽",
            "陪我理一理",
            "帮我想办法",
            "有点撑不住了",
        )
        for label in mode_labels:
            with self.subTest(label=label):
                self.assertIn(label, self.html)

    def test_support_and_privacy_structure_is_present(self):
        required_structure = (
            'id="support-btn"',
            'id="support-dialog"',
            "联系辅导员",
            "预约心理咨询",
            "紧急求助",
            "聊天会保存在会话历史中，但不会自动联系任何人或转交给真人。",
        )
        for item in required_structure:
            with self.subTest(item=item):
                self.assertIn(item, self.html)

    def test_legacy_human_transfer_is_removed(self):
        self.assertNotIn('id="human-btn"', self.html)
        self.assertNotIn("transferHuman", self.html)
        self.assertNotIn(".status-pill", self.html)
        self.assertNotIn("linear-gradient", self.html)

    def test_support_dialog_opening_has_no_network_side_effect(self):
        self.assertIn("function openSupportPanel", self.html)
        body = function_body(self.html, "openSupportPanel")
        self.assertIn("showModal", body)
        self.assertNotIn("fetch(", body)
        self.assertNotIn("api.", body)
        self.assertNotIn("/api/tickets", self.html)

    def test_support_dialog_uses_native_close_and_backdrop_bindings(self):
        self.assertIn('<dialog id="support-dialog"', self.html)
        self.assertIn("showModal", self.html)
        close_body = function_body(self.html, "closeSupportPanel")
        self.assertIn("supportDialog.close()", close_body)
        self.assertIn("supportDialog.removeAttribute('open')", close_body)
        self.assertIn("closeSupportBtn.onclick = closeSupportPanel;", self.html)
        self.assertIn("supportDialog.addEventListener('click', (event) => {", self.html)
        self.assertIn(
            "if (event.target === supportDialog) closeSupportPanel();",
            self.html,
        )

    def test_quick_prompts_use_the_existing_chat_flow(self):
        self.assertIn("function bindQuickPrompts", self.html)
        body = function_body(self.html, "bindQuickPrompts")
        self.assertIn("inputEl.value = button.dataset.prompt;", body)
        self.assertEqual(body.count("send();"), 1)
        self.assertNotIn("api", body)
        self.assertNotIn("fetch(", body)

    def test_chat_and_session_refresh_errors_are_isolated(self):
        self.assertIn("async function refreshSessionsSafely(activeId)", self.html)
        refresh_body = function_body(self.html, "refreshSessionsSafely")
        self.assertIn("try", refresh_body)
        self.assertIn("await loadSessions(activeId);", refresh_body)
        self.assertIn("catch (error)", refresh_body)
        self.assertIn("console.warn('会话列表刷新失败', error);", refresh_body)

        send_body = function_body(self.html, "send")
        self.assertIn("await refreshSessionsSafely(currentSessionId);", send_body)
        self.assertNotIn("await loadSessions(currentSessionId);", send_body)

    def test_send_flow_has_no_legacy_human_button_state(self):
        self.assertNotIn("transferHuman", self.html)
        body = function_body(self.html, "send")
        self.assertNotIn("humanBtn", body)
        self.assertIn("if (!content || loading || !currentSessionId) return;", body)
        self.assertIn("sendBtn.disabled = true;", body)
        self.assertIn("sendBtn.disabled = false;", body)
        self.assertIn(
            "我刚才没能接上，你可以再试一次。需要的话，也可以先找真人聊聊。",
            body,
        )

    def test_api_methods_use_shared_response_error_helper(self):
        self.assertIn("async function parseResponse(response) {", self.html)
        self.assertIn("let detail = '请求失败：' + response.status;", self.html)
        self.assertIn("return response.json();", self.html)
        self.assertNotIn(".then(r => r.json())", self.html)
        self.assertIn("function requestJson(url, options = {}, mode = authMode, token = authToken)", self.html)
        self.assertIn("headers.Authorization = 'Bearer ' + token;", self.html)
        self.assertIn("headers['X-Anonymous-Id'] = anonymousId;", self.html)

    def test_identity_modes_and_auth_controls_are_present(self):
        required_structure = (
            'id="identity-panel"',
            'id="auth-dialog"',
            'id="anonymous-mode-btn"',
            'id="account-mode-btn"',
            'id="auth-form"',
            'id="logout-btn"',
            "localStorage.getItem('youhua_anonymous_id')",
            "localStorage.setItem('youhua_auth_token', authToken)",
            "api.register",
            "api.login",
        )
        for item in required_structure:
            with self.subTest(item=item):
                self.assertIn(item, self.html)

    def test_identity_switch_refreshes_sessions_and_open_session_restores_messages(self):
        self.assertIn("async function switchToAnonymous()", self.html)
        self.assertIn("await createSession();", function_body(self.html, "switchToAnonymous"))
        register_body = function_body(self.html, "applyAccountAuth")
        self.assertIn("await openSession(currentSessionId);", register_body)
        open_body = function_body(self.html, "openSession")
        self.assertIn("const detail = await api.getSession(id);", open_body)
        self.assertIn("for (const m of detail.messages)", open_body)

    def test_create_session_synchronizes_location_hash(self):
        self.assertIn(
            "currentSessionId = s.session_id;\n  location.hash = `session-${s.session_id}`;",
            self.html,
        )

    def test_session_items_expose_explicit_current_state(self):
        self.assertIn(
            "div.setAttribute('aria-current', s.session_id === activeId ? 'page' : 'false');",
            self.html,
        )


if __name__ == "__main__":
    unittest.main()
