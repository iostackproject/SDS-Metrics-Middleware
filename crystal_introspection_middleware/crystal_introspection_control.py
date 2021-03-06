from threading import Thread
import time
import pika
import redis
import json

class Singleton:
    """
    A non-thread-safe helper class to ease implementing singletons.
    This should be used as a decorator -- not a metaclass -- to the
    class that should be a singleton.

    The decorated class can define one `__init__` function that
    takes only the `self` argument. Other than that, there are
    no restrictions that apply to the decorated class.

    To get the singleton instance, use the `Instance` method. Trying
    to use `__call__` will result in a `TypeError` being raised.

    Limitations: The decorated class cannot be inherited from.
    """

    def __init__(self, decorated):
        self._decorated = decorated

    def Instance(self, **args):
        """
        Returns the singleton instance. Upon its first call, it creates a
        new instance of the decorated class and calls its `__init__` method.
        On all subsequent calls, the already created instance is returned.

        """
        logger = args['log']
        try:
            if self._instance:
                logger.info("Crystal - Singleton instance of introspection"
                            " control already created")
                return self._instance
        except AttributeError:
            logger.info("Crystal - Creating singleton instance of"
                        " introspection control")
            self._instance = self._decorated(**args)
            return self._instance

    def __call__(self):
        raise TypeError('Singletons must be accessed through `Instance()`.')

    def __instancecheck__(self, inst):
        return isinstance(inst, self._decorated)


@Singleton
class CrystalIntrospectionControl():
    def __init__(self, conf, log):
        self.logger = log
        self.conf = conf
        
        self.control_thread = ControlThread(self.conf)
        self.control_thread.daemon = True
        
        self.publish_thread = PublishThread(self.conf)
        self.publish_thread.daemon = True
        
        self.threads_started = False

    def get_metrics(self):
        return self.control_thread.metric_list 
    
    def publish_stateful_metric(self,routing_key, key, value):
        self.publish_thread.publish_statefull(routing_key, key, value)
    
    def publish_stateless_metric(self,routing_key, key, value):
        self.publish_thread.publish_stateless(routing_key, key, value)
        
class PublishThread(Thread):
    
    def __init__(self, conf):
        Thread.__init__(self)
        
        self.monitoring_statefull_data = dict()
        self.monitoring_stateless_data = dict()
        
        self.interval = conf.get('publish_interval',1.01)
        self.ip = conf.get('bind_ip')+":"+conf.get('bind_port')
        self.exchange = conf.get('exchange', 'amq.topic')
        
        rabbit_host = conf.get('rabbit_host')
        rabbit_port = int(conf.get('rabbit_port'))
        rabbit_user = conf.get('rabbit_username')
        rabbit_pass = conf.get('rabbit_password')

        credentials = pika.PlainCredentials(rabbit_user,rabbit_pass)  
        self.parameters = pika.ConnectionParameters(host = rabbit_host,
                                                    port = rabbit_port,
                                                    credentials = credentials)
      
    def publish_statefull(self, routing_key, key, value):
        if not routing_key in self.monitoring_statefull_data:
            self.monitoring_statefull_data[routing_key] = dict()
            if not key in self.monitoring_statefull_data[routing_key]:
                self.monitoring_statefull_data[routing_key][key] = 0
                
        self.monitoring_statefull_data[routing_key][key] += value
            
    def publish_stateless(self, routing_key, key, value):
        if not routing_key in self.monitoring_stateless_data:
            self.monitoring_stateless_data[routing_key] = dict()
            if not key in self.monitoring_stateless_data[routing_key]:
                self.monitoring_stateless_data[routing_key][key] = 0
                
        self.monitoring_stateless_data[routing_key][key] += value
       
    def run(self):
        data = dict()
        while True:
            time.sleep(self.interval)
            rabbit = pika.BlockingConnection(self.parameters)
            channel = rabbit.channel()
            
            for routing_key in self.monitoring_stateless_data.keys():
                data[self.ip] = self.monitoring_stateless_data[routing_key].copy()
                
                for key in self.monitoring_stateless_data[routing_key].keys():
                    if self.monitoring_stateless_data[routing_key][key] == 0:
                        del self.monitoring_stateless_data[routing_key]
                    else:
                        self.monitoring_stateless_data[routing_key][key] = 0
                        
                channel.basic_publish(exchange=self.exchange, 
                                      routing_key=routing_key, 
                                      body=json.dumps(data))
                
            for routing_key in self.monitoring_statefull_data.keys():
                data[self.ip] = self.monitoring_statefull_data[routing_key].copy()
                        
                channel.basic_publish(exchange=self.exchange, 
                                      routing_key=routing_key, 
                                      body=json.dumps(data))
                
     
class ControlThread(Thread):
    
    def __init__(self, conf):
        Thread.__init__(self)

        self.interval = conf.get('control_interval',10)
        redis_host = conf.get('redis_host')
        redis_port = conf.get('redis_port')
        redis_db = conf.get('redis_db')
        
        self.redis = redis.StrictRedis(redis_host, 
                                       redis_port, 
                                       redis_db)
        
        self.metric_list = {}
      
    def run(self):
        while True:
            self.metric_list = self.redis.hgetall("metrics")
            time.sleep(self.interval)