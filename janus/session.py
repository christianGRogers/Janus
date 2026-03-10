import requests
from . import const
from . import node as n

class Session:
    def __init__(self, id, user_id, token, created_at, broker_url, datastream_url):
        self.id = id
        self.user_id = user_id
        self.token = token
        self.created_at = created_at
        self.broker_url = broker_url
        self.datastream_url = datastream_url
        # node assigned to this session (instance of node.Node)
        self.node = None

    def __str__(self):
        return (
            f"Session(id={self.id}, user_id={self.user_id}, "
            f"broker_url={self.broker_url}, datastream_url={self.datastream_url})"
        )

    def add_inference_model(self, model, model_type=None):
        """
        Add a trained model for inference.
        
        Args:
            model: The trained model object (PyTorch, TensorFlow, scikit-learn, etc.)
            model_type: Optional string to specify model framework
        """
        self.inference_model = model
        self.model_type = model_type or self._detect_model_type(model)
    
    def _detect_model_type(self, model):
        """Detect the type of model framework."""
        model_class = type(model).__name__
        module_name = type(model).__module__
        
        if 'torch' in module_name:
            return 'pytorch'
        elif 'tensorflow' in module_name or 'keras' in module_name:
            return 'tensorflow'
        elif 'sklearn' in module_name:
            return 'scikit-learn'
        elif 'xgboost' in module_name:
            return 'xgboost'
        elif 'lightgbm' in module_name:
            return 'lightgbm'
        else:
            return 'unknown'
    
    def request_node(self):
        """Request an available node for this session via REST API.

        The server automatically assigns the first available node – the
        client does not choose.  On success the assigned node is stored
        in ``self.node`` and the full response dict is returned.
        """
        endpoint = const.BRADENSBAY_API_URL + "/sessions/request_node"
        payload = {
            "session_id": self.id,
        }
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }

        try:
            response = requests.post(endpoint, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
            self.node = n.Node(
                id=data["node_id"],
                status="assigned",
            )
            print(f"Session {self.id} assigned to node {data['node_id']}")
            return data
        except requests.exceptions.RequestException as e:
            print(f"Failed to request node: {e}")
            raise

    def run_model(self, model_id, input_data=None):
        """Run financial inference on a deployed model.

        By default the session's ``datastream_url`` is used to pull live
        market data and the ``broker_url`` receives the resulting trade
        signals.  Pass *input_data* (2-D list of floats) to override the
        data stream for back-testing or offline evaluation.

        Returns the full response dict including ``predictions``,
        ``broker_url``, and ``broker_dispatched``.
        """
        endpoint = const.BRADENSBAY_API_URL + f"/models/{model_id}/run"
        body = {
            "datastream_url": self.datastream_url,
            "broker_url": self.broker_url,
        }
        if input_data is not None:
            body["input_data"] = input_data
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

        try:
            response = requests.post(endpoint, json=body, headers=headers)
            response.raise_for_status()
            data = response.json()
            print(
                f"Model {model_id}: {len(data.get('predictions', []))} predictions "
                f"→ broker_dispatched={data.get('broker_dispatched', False)}"
            )
            return data
        except requests.exceptions.RequestException as e:
            print(f"Failed to run model: {e}")
            raise