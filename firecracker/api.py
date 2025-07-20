import requests
import urllib.parse
from http import HTTPStatus
from .exceptions import APIError
from requests_unixsocket import UnixAdapter

DEFAULT_SCHEME = "http://"


class Session(requests.Session):
    """An HTTP over UNIX sockets Session with optimized connection pooling"""
    def __init__(self):
        """Create a Session object."""
        super().__init__()
        adapter = UnixAdapter(
            pool_connections=20,
            pool_maxsize=20,
            max_retries=3,
            pool_block=True
        )
        self.mount(DEFAULT_SCHEME, adapter)


class Resource:
    """An abstraction over a REST path"""

    def __init__(self, api, resource, id_field=None):
        """Initialize a REST resource.

        Args:
            api (Api): The API client instance
            resource (str): The resource path
            id_field (str, optional): The field name used for resource ID
        """
        self._api = api
        self.resource = resource
        self.id_field = id_field

    def get(self):
        """Make a GET request.

        Returns:
            requests.Response: The HTTP response

        Raises:
            APIError: If the request fails or returns an error response
        """
        try:
            url = self._api.endpoint + self.resource
            with self._api.session.get(url) as res:
                if res.status_code != HTTPStatus.OK:
                    json = res.json()
                    if "fault_message" in json:
                        raise APIError(f"API fault: {json['fault_message']}")
                    elif "error" in json:
                        raise APIError(f"API error: {json['error']}")
                    raise APIError(f"Unexpected response: {res.content}")

                return res

        except requests.RequestException as e:
            raise APIError(f"GET request failed: {str(e)}") from e
        except ValueError as e:
            raise APIError(f"Invalid JSON response: {str(e)}") from e

    def put(self, **kwargs):
        """Make a PUT request.

        Args:
            **kwargs: Key-value pairs for the request body

        Returns:
            requests.Response: The HTTP response
        """
        path = self.resource
        if self.id_field is not None:
            path += "/" + kwargs[self.id_field]
        return self.request("PUT", path, **kwargs)

    def patch(self, **kwargs):
        """Make a PATCH request.

        Args:
            **kwargs: Key-value pairs for the request body

        Returns:
            requests.Response: The HTTP response
        """
        path = self.resource
        if self.id_field is not None:
            path += "/" + kwargs[self.id_field]
        return self.request("PATCH", path, **kwargs)

    def request(self, method, path, **kwargs):
        """Make an HTTP request to the Firecracker API.

        Args:
            method (str): HTTP method (GET, PUT, POST, DELETE, etc.)
            path (str): API endpoint path
            **kwargs: Additional arguments to be sent as JSON in request body

        Returns:
            requests.Response: The HTTP response from the API

        Raises:
            APIError: If the request fails or returns an error response
        """
        try:
            kwargs = {key: val for key, val in kwargs.items() if val is not None}
            url = self._api.endpoint + path
            with self._api.session.request(method, url, json=kwargs) as res:
                if res.status_code != HTTPStatus.NO_CONTENT:
                    json = res.json()
                    if "fault_message" in json:
                        raise APIError(f"API fault: {json['fault_message']}")
                    elif "error" in json:
                        raise APIError(f"API error: {json['error']}")
                    raise APIError(f"Unexpected response: {res.content}")

                return res

        except requests.RequestException as e:
            raise APIError(f"Request failed: {str(e)}") from e
        except ValueError as e:
            raise APIError(f"Invalid JSON response: {str(e)}") from e


class Api:
    """A simple HTTP client for the Firecracker API"""
    def __init__(self, socket_file):
        self.socket = socket_file
        url_encoded_path = urllib.parse.quote_plus(socket_file)
        self.endpoint = DEFAULT_SCHEME + url_encoded_path
        self.session = Session()

        self.describe = Resource(self, "/")
        self.vm = Resource(self, "/vm")
        self.vm_config = Resource(self, "/vm/config")
        self.actions = Resource(self, "/actions")
        self.boot = Resource(self, "/boot-source")
        self.drive = Resource(self, "/drives", "drive_id")
        self.version = Resource(self, "/version")
        self.logger = Resource(self, "/logger")
        self.machine_config = Resource(self, "/machine-config")
        self.network = Resource(self, "/network-interfaces", "iface_id")
        self.mmds = Resource(self, "/mmds")
        self.mmds_config = Resource(self, "/mmds/config")
        self.create_snapshot = Resource(self, "/snapshot/create")
        self.load_snapshot = Resource(self, "/snapshot/load")
        self.vsock = Resource(self, "/vsock")

    def close(self):
        """Close the session to release resources."""
        self.session.close()
