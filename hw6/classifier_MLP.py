import torch
import numpy as np
import torch.nn as nn
import torch.nn.functional as F
import torchvision
import torchvision.transforms as transforms
import matplotlib.pyplot as plt
from hdf5_dataset import HDF5Dataset
import argparse
from time import time
import seaborn as sns
import pandas as pd
from sklearn.metrics import confusion_matrix
from pathlib import Path

def str2bool(v):
    if isinstance(v, bool):
        return v
    if v.lower() in ('yes', 'true', 't', 'y', '1'):
        return True
    elif v.lower() in ('no', 'false', 'f', 'n', '0'):
        return False
    else:
        raise argparse.ArgumentTypeError('Boolean value expected.')

def init_parser(parser):

    parser.add_argument('--dataset',
                        type=str.lower,
                        choices=['mnist', 'fmnist', 'cifar10'],
                        default='mnist')
    parser.add_argument('--device', type=str, default='gpu')
    parser.add_argument('--max_epoch', default=50, type=int)
    parser.add_argument('--lr', default=1e-2, type=float)
    #parser.add_argument('--decay_lr', default=False, type=str2bool)
    #parser.add_argument('--decay_position',  nargs='+', type=int, default=[25])
    parser.add_argument('--shuffle', default=True, type=str2bool)
    parser.add_argument('--train_method', type=str, choices=['SGD'], default='SGD')
    parser.add_argument('--reg', type=float, default=1e-4) #default L2 regularization
    parser.add_argument('--batch_size', type=int, default=100)
    parser.add_argument('--print_freq', type=int, default=500)
    parser.add_argument('--class_num', type=int, default=10)
    parser.add_argument('--activation', type=str, choices=['relu'], default='relu')
    parser.add_argument('--model', type=str, default='m1', choices=['m1', 'm2', 'm3'])
    parser.add_argument('--layer_model1', nargs='+', type=int, default=[]) #only hidden layer
    parser.add_argument('--layer_model2', nargs='+', type=int, default=[128]) #only hidden layer
    parser.add_argument('--layer_model3', nargs='+', type=int, default=[256, 128])  # only hidden layer
    parser.add_argument('--dropout', type=float, default=0)
    parser.add_argument('--confusion_matrix', type=str2bool, default=True)
    parser.add_argument('--plot_learning_curve', default=True, type=str2bool)
    parser.add_argument('--plot_weight_hist', default=False, type=str2bool)

    return parser

#define the model
class MLP1(nn.Module):
    def __init__(self, input_dim=784, allargs=None,):
        super(MLP1, self).__init__()
        self.output = nn.Linear(input_dim, allargs.class_num)
        self.dropout = nn.Dropout(p=allargs.dropout)

    def forward(self, x):
        x = self.dropout(x)
        x = self.output(x)
        return x

class MLP2(nn.Module):
    def __init__(self, input_dim=784, allargs=None,):
        super(MLP2, self).__init__()
        self.layer1 = nn.Linear(input_dim, allargs.layer_model2[0])
        if allargs.activation == 'relu':
            self.activation = nn.ReLU()
        self.output = nn.Linear(allargs.layer_model2[0], allargs.class_num)
        self.dropout = nn.Dropout(p=allargs.dropout)

    def forward(self, x):
        x = self.layer1(x)
        x = self.activation(x)
        x = self.dropout(x)
        x = self.output(x)
        return x

class MLP3(nn.Module):
    def __init__(self, input_dim=3072, allargs=None,):
        super(MLP3, self).__init__()
        self.layer1 = nn.Linear(input_dim, allargs.layer_model3[0])
        if allargs.activation == 'relu':
            self.activation = nn.ReLU()
        self.layer2 = nn.Linear(allargs.layer_model3[0], allargs.layer_model3[1])
        self.output = nn.Linear(allargs.layer_model3[1], allargs.class_num)
        self.dropout = nn.Dropout(p=allargs.dropout)

    def forward(self, x):
        x = self.layer1(x)
        x = self.activation(x)
        x = self.dropout(x)
        x = self.layer2(x)
        x = self.activation(x)
        x = self.dropout(x)
        x = self.output(x)
        return x

def accuracy(output, target, args):
    with torch.no_grad():
        batch_size = target.size(0)

        _, pred = output.topk(1, 1, True, True)
        pred = pred.t()

        if args.dataset == 'mnist':
            target = torch.argmax(target, dim=1)
        correct = pred.eq(target.view(1, -1).expand_as(pred))

        res = []
        correct_k = correct[:1].flatten().float().sum(0, keepdim=True)
        res.append(correct_k.mul_(100.0 / batch_size))
        return res

def train_epoch(device, trainloader, model, criterion, optimizer, epoch, args):
    model.train()
    loss_sum, acc1_num_sum = 0, 0
    num_input_sum = 0
    for batch_idx, (images, target) in enumerate(trainloader):
        shp = images.shape
        pixel_num = 1
        for i in range(1, len(shp)):
            pixel_num *= shp[i]

        images = images.view(-1, pixel_num)
        images, target = images.to(device), target.to(device)

        output = model(images)
        #print (f"output: {output.shape}")

        loss = criterion(output, target)

        acc1 = accuracy(output, target, args)
        num_input_sum += images.shape[0]
        loss_sum += float(loss.item() * images.shape[0])
        acc1_num_sum += float(acc1[0] * images.shape[0])

        optimizer.zero_grad()

        loss.backward()

        optimizer.step()

        #scheduler.step()


        if batch_idx % args.print_freq == 0:
            avg_loss, avg_acc1 = (loss_sum / num_input_sum), (acc1_num_sum / num_input_sum)
            print(f'[Epoch {epoch + 1}][Train][{batch_idx}] \t Loss: {avg_loss:.4e} \t Top-1 {avg_acc1:6.2f}')

    avg_loss, avg_acc1 = (loss_sum / num_input_sum), (acc1_num_sum / num_input_sum)
    return avg_loss, avg_acc1

def validate(device, testloader, model, criterion, epoch, args, time_begin):
    model.eval()
    loss_sum, acc_num_sum = 0, 0
    num_input_sum = 0
    pred = np.array([])
    tar = np.array([])
    with torch.no_grad():
        for batch_idx, (images, target) in enumerate(testloader):
            shp = images.shape
            pixel_num = 1
            for i in range(1, len(shp)):
                pixel_num *= shp[i]

            images = images.view(-1, pixel_num)
            images, target = images.to(device), target.to(device)

            output = model(images)
            loss = criterion(output, target)

            # for confusion matrix
            pred = np.concatenate((pred, np.argmax(output.cpu().detach().numpy(), axis=1)))
            if args.dataset == 'mnist':
                tar = np.concatenate((tar, np.argmax(target.cpu().detach().numpy(), axis=1)))
            else:
                tar = np.concatenate((tar, target.cpu().detach().numpy()))

            acc1 = accuracy(output, target, args)
            num_input_sum += images.shape[0]
            loss_sum += float(loss.item() * images.shape[0])
            acc_num_sum += float(acc1[0] * images.shape[0])

            if batch_idx % args.print_freq == 0:
                avg_loss, avg_acc1 = (loss_sum / num_input_sum), (acc_num_sum / num_input_sum)
                print(f'[Epoch {epoch + 1}][Eval][{batch_idx}] \t Loss: {avg_loss:.4e} \t Top-1 {avg_acc1:6.2f}')


    avg_loss, avg_acc = (loss_sum / num_input_sum), (acc_num_sum / num_input_sum)
    total_mins = -1 if time_begin is None else (time() - time_begin) / 60
    print(f'[Epoch {epoch + 1}] \t \t Top-1 {avg_acc:6.2f} \t \t Time: {total_mins:.2f}')

    return avg_loss, avg_acc, pred, tar

def load_checkpoint(checkpoint_pthpath):
    if isinstance(checkpoint_pthpath, str):
        checkpoint_pthpath = Path(checkpoint_pthpath)
    checkpoint_dirpath = checkpoint_pthpath.resolve().parent
    checkpoint_commit_sha = list(checkpoint_dirpath.glob(".commit-*"))
    components = torch.load(checkpoint_pthpath)
    return components["model"], components["optimizer"]

def train(args):
    #use gpus
    if args.device=='gpu' and torch.cuda.is_available():
        device = torch.device("cuda")
        print(f'There are {torch.cuda.device_count()} GPU(s) available.')
        print('Device name:', torch.cuda.get_device_name(0))
    else:
        print('No GPU available, using the CPU instead.')
        device = torch.device("cpu")
    print (f'config: {args}')

    # load datasets
    if args.dataset == 'mnist':
        DATA_PTH = './data/mnist/'
        train_set = HDF5Dataset(file_path=f"{DATA_PTH}mnist_traindata.hdf5", data_name='xdata', label_name='ydata')
        test_set = HDF5Dataset(file_path=f"{DATA_PTH}mnist_testdata.hdf5", data_name='xdata', label_name='ydata')
        in_dim = 784
    elif args.dataset == 'fmnist':
        DATA_PTH = './data/Fmnist/'
        train_set = torchvision.datasets.FashionMNIST(root=DATA_PTH, train=True, download=True, transform=transforms.ToTensor())
        test_set = torchvision.datasets.FashionMNIST(root=DATA_PTH, train=False, download=True, transform=transforms.ToTensor())
        in_dim = 784
    elif args.dataset == 'cifar10':
        DATA_PTH = './data/Cifar10/'
        train_set = torchvision.datasets.CIFAR10(root=DATA_PTH, train=True, download=True, transform=transforms.ToTensor())
        test_set = torchvision.datasets.CIFAR10(root=DATA_PTH, train=False, download=True, transform=transforms.ToTensor())
        in_dim = 3072
    trainloader = torch.utils.data.DataLoader(train_set, batch_size=args.batch_size, shuffle=args.shuffle)
    testloader = torch.utils.data.DataLoader(test_set, batch_size=100, shuffle=False)

    #define model
    if args.model == 'm1':
        model = MLP1(input_dim=in_dim, allargs=args)
    elif args.model == 'm2':
        model = MLP2(input_dim=in_dim, allargs=args)
    elif args.model == 'm3':
        model = MLP3(input_dim=in_dim, allargs=args)

    model.to(device)

    #define Optimizer & Loss function
    criterion = nn.CrossEntropyLoss()
    criterion.to(device)

    optimizer = torch.optim.SGD(model.parameters(), lr=args.lr, weight_decay=args.reg)

    #start training
    train_loss_list = []
    train_acc_list = []
    val_loss_list = []
    val_acc_list = []
    time_begin = time()
    best_val_acc = 0
    for epoch in range(args.max_epoch):
        train_loss, train_acc = train_epoch(device, trainloader, model, criterion, optimizer, epoch, args)
        val_loss, val_acc, _,_ = validate(device, testloader, model, criterion, epoch, args, time_begin)

        train_loss_list.append(train_loss)
        train_acc_list.append(train_acc)
        val_loss_list.append(val_loss)
        val_acc_list.append(val_acc)


        if val_acc > best_val_acc:
            print(f"save model")
            best_val_acc = val_acc
            torch.save(
                {
                    "model": model.state_dict(),
                    "optimizer": optimizer.state_dict(),
                },
                f"./model/best_model_dataset_{args.dataset}.pth",
            )

    print(f'config: {args}')
    total_mins = (time() - time_begin) / 60
    print(f'Script finished in {total_mins:.2f} minutes, '
          f'best top-1: {best_val_acc:.2f}, '
          f'final top-1: {val_acc:.2f}')

    if args.plot_learning_curve:
        plt.figure()
        x = np.arange(1, args.max_epoch+1)
        plt.plot(x, train_acc_list, label="train_acc", color='b')
        plt.ylabel("acc")
        plt.title("Train and validation/test acc vs iterations")
        plt.plot(x, val_acc_list, label="validation/test_acc", color='r')
        plt.legend()
        plt.show()

        plt.figure()
        x = np.arange(1, args.max_epoch + 1)
        plt.plot(x, train_loss_list, label="train_log_loss", color='b')
        plt.ylabel("log_loss")
        plt.title("Train and validation/test log_loss vs iterations")
        plt.plot(x, val_loss_list, label="validation/test_log_loss", color='r')
        plt.legend()
        plt.show()

    if args.model == 'm1':
        model_pred = MLP1(input_dim=in_dim, allargs=args)
    elif args.model == 'm2':
        model_pred = MLP2(input_dim=in_dim, allargs=args)
    elif args.model == 'm3':
        model_pred = MLP3(input_dim=in_dim, allargs=args)

    model_pred.to(device)
    model_state_dict, optimizer_state_dict = load_checkpoint(f'./model/best_model_dataset_{args.dataset}.pth')
    model_pred.load_state_dict(model_state_dict)

    if args.confusion_matrix:
        _, _, pred, tar = validate(device, testloader, model_pred, criterion, epoch, args, time_begin)
        cm = confusion_matrix(tar, pred)
        conf_matrix = pd.DataFrame(cm, index=['0', '1', '2', '3', '4', '5', '6', '7', '8', '9'],
                                   columns=['0', '1', '2', '3', '4', '5', '6', '7', '8', '9'])
        sns.heatmap(conf_matrix, annot=True, annot_kws={"size": 14}, cmap="Blues")
        plt.ylabel('True label', fontsize=14)
        plt.xlabel('Predicted label', fontsize=14)
        plt.xticks(fontsize=14)
        plt.yticks(fontsize=14)
        plt.show()

    if args.plot_weight_hist:
        # for name in model_pred.state_dict():
        #     print(name)
        weights1 = model_pred.state_dict()['layer1.weight']
        sns.set_style("darkgrid")
        sns.displot(weights1.cpu().detach().numpy().flatten(), color='b')
        plt.xlim(-1, 1)
        plt.show()

        weights2 = model.state_dict()['output.weight']
        sns.set_style("darkgrid")
        sns.displot(weights2.cpu().detach().numpy().flatten(), color='b')
        plt.xlim(-1, 1)
        plt.show()


if __name__ == '__main__':

    parser = argparse.ArgumentParser(description='MLP training script')

    parser=init_parser(parser)

    args = parser.parse_args()

    train(args)

