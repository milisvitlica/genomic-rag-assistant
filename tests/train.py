import torch
import mlflow

mlflow.set_tracking_uri("sqlite:///mlflow.db")

mlflow.start_run()

x = torch.tensor([1,2,3])
y = x*2

mlflow.log_param("model", "test_model")
mlflow.log_metric("sum", y.sum().item())


mlflow.end_run()