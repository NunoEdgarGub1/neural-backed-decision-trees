from utils.datasets import Node
import torch
import torch.nn as nn
import os


__all__ = ('CIFAR10Tree', 'CIFAR10JointNodes', 'CIFAR10JointTree')


def load_checkpoint(net, path):
    if not os.path.exists(path):
        print(f' * Failed to load model. No such path found: {path}')
        return
    checkpoint = torch.load(path)
    # hacky fix lol
    state_dict = {key.replace('module.', '', 1): value for key, value in checkpoint['net'].items()}
    net.load_state_dict(state_dict)


class CIFAR10Tree(nn.Module):
    """returns samples from all node classifiers"""

    def __init__(self, *args,
            path_tree='./data/cifar10/tree.xml',
            path_wnids='./data/cifar10/wnids.txt',
            pretrained=True,
            num_classes=10,
            one_hot_feature=False,
            **kwargs):
        super().__init__()

        self.nodes = Node.get_nodes(path_tree, path_wnids)
        self.nets = nn.ModuleList([
            self.get_net_for_node(node, pretrained) for node in self.nodes])

        self.one_hot_feature = one_hot_feature
        self.linear = nn.Linear(self.get_input_dim(), num_classes)

    def get_net_for_node(self, node, pretrained):
        import models
        # TODO: WARNING: the model and paths are hardcoded
        net = models.ResNet10(num_classes=len(node.classes))

        if pretrained:
            load_checkpoint(net, f'./checkpoint/ckpt-CIFAR10Node-ResNet10-{node.wnid}.pth')
        return net

    def get_input_dim(self):
        return Node.dim(self.nodes)

    def forward(self, old_sample):
        with torch.no_grad():
            sample = []
            for net in self.nets:
                feature = net(old_sample)

                if self.one_hot_feature:
                    maximum = torch.max(feature, dim=1)[0]
                    feature = (feature == maximum[:, None]).float()
                sample.append(feature)
            sample = torch.cat(sample, 1)
        return self.linear(sample)


class CIFAR10JointNodes(nn.Module):
    """
    Requires that model have a featurize method. Like training individual nodes,
    except all nodes share convolutions. Thus, all nodes are trained jointly.
    """

    def __init__(self, *args,
            path_tree='./data/cifar10/tree.xml',
            path_wnids='./data/cifar10/wnids.txt',
            num_classes=None,  # ignored
            **kwargs):
        super().__init__()

        import models
        # hardcoded for ResNet10
        self.net = models.ResNet10()
        self.nodes = Node.get_nodes(path_tree, path_wnids)
        self.heads = nn.ModuleList([
            # hardcoded for ResNet10
            nn.Linear(512, len(node.classes))
            for node in self.nodes
        ])

    def custom_loss(self, criterion, outputs, targets):
        loss = 0
        for output, target in zip(outputs, targets.T):
            loss += criterion(output, target)
        return loss

    def custom_prediction(self, outputs):
        preds = []
        for output in outputs:
            _, pred = output.max(dim=1)
            preds.append(pred[:, None])
        predicted = torch.cat(preds, dim=1)
        return predicted

    def forward(self, x):
        """Note this returns unconventional output.

        The output is (h, n, k) for h heads (number of trainable nodes in the
        tree), n samples, and k classes.
        """
        assert hasattr(self.net, 'featurize'), \
            'Net needs a `featurize` method to work with CIFAR10JointNodes ' \
            'training'
        x = self.net.featurize(x)

        outputs = []
        for head in self.heads:
            outputs.append(head(x))
        return outputs


class CIFAR10JointTree(nn.Module):
    """
    Final classifier for the nodes trained jointly above, in the
    CIFAR10JointNodes model
    """

    def __init__(self, *args,
            path_tree='./data/cifar10/tree.xml',
            path_wnids='./data/cifar10/wnids.txt',
            num_classes=10,
            pretrained=True,
            **kwargs):
        super().__init__()

        self.net = CIFAR10JointNodes(*args, path_tree, path_wnids, **kwargs)
        if pretrained:
            load_checkpoint(self.net, './checkpoint/ckpt-CIFAR10JointNodes-CIFAR10JointNodes.pth')
        self.linear = nn.Linear(Node.dim(self.net.nodes), num_classes)

    def forward(self, x):
        with torch.no_grad():
            x = self.net(x)
        x = torch.cat(x, dim=1)
        x = self.linear(x)
        return x
