from copy import deepcopy

import numpy as np

# pytorch import
import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.nn.utils as torch_utils

# pytorch ignite import
from ignite.engine import Engine
from ignite.engine import Events
from ignite.metrics import RunningAverage
from ignite.contrib.handlers.tqdm_logger import ProgressBar

from utils import get_grad_norm,get_parameter_norm

VERBOSE_BATCH_WISE = 2
VERBOSE_EPOCH_WISE = 1
VERBOSE_SILENT = 0

class MyEngine(Engine):
    def __init__(self,func,model,crit,optimizer,config):
        self.model=model
        self.crit=crit
        self.optimizer=optimizer
        self.config=config

        super().__init__(func)

        self.best_loss = np.inf
        self.best_model = None

        self.device = next(model.parameters()).device

    @staticmethod
    def train(engine,mini_batch):
        engine.model.train()
        engine.optimizer.zero_grad()

        x,y = mini_batch
        x,y = x.to(engine.device) , y.to(engine.device)

        y_hat = engine.model(x)

        loss = engine.crit(y_hat,y)
        loss.backward()

        if isinstance(y,torch.LongTensor) or isinstance(y,torch.cuda.LongTensor):
            accuracy = (torch.argmax(y_hat,dim=-1)==y).sum() / float(y.shape[0])
        else:
            accuracy = 0

        p_norm = get_parameter_norm(engine.model.parameters())
        g_norm = get_grad_norm(engine.model.parameters())

        engine.optmizer.step()

        return {
            'loss' : float(loss),
            'accuract' : accuracy,
            '|param|':p_norm,
            '|g_param|':g_norm
        }

    @staticmethod
    def validate(engine,mini_batch):
        engine.model.eval()
        
        with torch.no_grad():
            x,y = mini_batch
            x,y = x.to(engine.device),y.to(engine.device)

            y_hat = engine.model(x)

            loss = engine.crit(y_hat,y)

            if isinstance(y,torch.LongTensor) or isinstance(y,torch.cuda.LongTensor):
                accuracy = (torch.argmax(y_hat,dim=-1)==y).sum() / float(y.shape[0])
            else:
                accuracy = 0

            return {
                'loss' : float(loss),
                'accuracy' : accuracy
            }

    @staticmethod
    def attach(train_engine,valid_engine,verbose=VERBOSE_BATCH_WISE):
        def attach_running_average(engine,metric_name):
            RunningAverage(output_transform=lambda x : x[metric_name]).attach(
                engine,
                metric_name
            )

        training_metric_names = ['loss','accuracy','|param|','|g_param|']

        for metric_name in training_metric_names:
            attach_running_average(train_engine,metric_name)

        if verbose >= VERBOSE_BATCH_WISE:
            pbar = ProgressBar(bar_format=None,ncols=120)
            pbar.attach(train_engine,training_metric_names)

        if verbose >= VERBOSE_EPOCH_WISE:
            @train_engine.on(Events.EPOCH_COMPLETED)
            def print_train_logs(engine):
                print('EPOCH {} - |param|={:.2e} |g_param|={:.2e} loss={:.4e} accuracy={:.4f}'.format(
                    engine.state.epoch,
                    engine.state.metrics['|param|'],
                    engine.state.metrics['|g_param|'],
                    engine.state.metrics['loss'],
                    engine.state.metrics['accuracy'],
                ))
            
        validation_metric_names=['loss','accuracy']

        for metric_name in validation_metric_names:
            attach_running_average(valid_engine,metric_name)

        if verbose >= VERBOSE_BATCH_WISE:
            pbar = ProgressBar(bar_format=None,ncols=120)
            pbar.attach(valid_engine,validation_metric_names)
        
        if verbose >= VERBOSE_EPOCH_WISE:
            @valid_engine.on(Events.EPOCH_COMPLETED)
            def print_valid_logs(engine):
                print('Validate - loss={:.4e} accuracy={:.4f} best_loss={:.4e}'.format(
                    engine.state.metrics['loss'],
                    engine.state.metrics['accuracy'],
                    engine.best_loss
                ))

    
    @staticmethod
    def check_best(engine):
        loss = float(engine.state.metrics['loss'])
        if loss <= engine.best_loss:
            best_loss = loss
            best_model = deepcopy(engine.model.state_dict())
    
    @staticmethod
    def save_model(engine,train_engine,config,**kwargs):
        torch.save(
            {
            'model' : engine.best_model,
            'config':config
            },config.model_fn
        )
