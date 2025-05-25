from rocketchat_API.rocketchat import RocketChat

class Rocket:
    def __init__(self, host: str, user: str, password: str, chat_id: str) -> None:
        self.rocket = RocketChat(
            server_url  = host,
            user_id     = user,
            auth_token  = password
        )
        self.chat_id = chat_id
        
    def send_message(self, message: str, thread_id: str | None = None) -> None:
        if thread_id:
            self.rocket.chat_post_message(message, room_id=self.chat_id, thread_id=thread_id)
        else:
            self.rocket.chat_post_message(message, room_id=self.chat_id)