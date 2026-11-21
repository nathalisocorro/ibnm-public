from confluent_kafka import Producer
import os


conf = {
    "bootstrap.servers": os.getenv(
        "KAFKA_BOOTSTRAP_SERVERS",
        "172.19.0.1:9092,172.19.0.1:9093,172.19.0.1:9094"
    ),
    "client.id": "my-python-producer"
}

producer = Producer(conf)

print(f"[kafka_producer] producer después de crear: {producer}", flush=True)
print(f"[kafka_producer] conf después: {conf}", flush=True)

def delivery_report(err, msg):
    """Callback for delivery reports."""
    if err is not None:
        print(f'Message delivery failed: {err}')
    else:
        print(f'Message delivered to {msg.topic()} [{msg.partition()}]')


