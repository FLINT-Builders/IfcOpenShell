import logging
from collections.abc import Callable

from fastapi import Request, Response
from fastapi.routing import APIRoute
from starlette.background import BackgroundTask
from starlette.responses import StreamingResponse


def log_info(req_body, res_body, route_url):
    logging.info("request:" + route_url + ":" + str(req_body))
    logging.info("response:" + route_url + ":" + str(res_body))


class LoggingRoute(APIRoute):
    log_bodies = True

    def get_route_handler(self) -> Callable:
        original_route_handler = super().get_route_handler()
        log_bodies = self.log_bodies

        async def custom_route_handler(request: Request) -> Response:
            req_body = await request.body() if log_bodies else b"<not logged>"
            response = await original_route_handler(request)
            # Query strings are left out because they can carry credentials and session identifiers.
            route_url = request.method + " " + request.url.path
            if not log_bodies:
                response.background = BackgroundTask(log_info, req_body, response.status_code, route_url)
                return response
            if isinstance(response, StreamingResponse):
                res_body = b""
                async for item in response.body_iterator:
                    res_body += item
                task = BackgroundTask(log_info, req_body, res_body, route_url)
                return Response(
                    content=res_body,
                    status_code=response.status_code,
                    headers=dict(response.headers),
                    media_type=response.media_type,
                    background=task,
                )
            else:
                if hasattr(response, "body"):
                    res_body = response.body
                else:
                    res_body = {"no response": True}
                response.background = BackgroundTask(log_info, req_body, res_body, route_url)
                return response

        return custom_route_handler


class CredentialRoute(LoggingRoute):
    """For routes whose request or response bodies carry passwords, authorization codes or tokens."""

    log_bodies = False


logging.basicConfig(filename="logs/info.log", level=logging.DEBUG)
