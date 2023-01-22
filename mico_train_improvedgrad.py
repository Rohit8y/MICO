# -*- coding: utf-8 -*-
"""mico_train_improvedgrad.ipynb

Automatically generated by Colaboratory.

Original file is located at
    https://colab.research.google.com/drive/1stu0WnbqdkdL9Ff13llrJ3cSWQENXMz_
"""

import os
import urllib

from torchvision.datasets.utils import download_and_extract_archive

url = "https://membershipinference.blob.core.windows.net/mico/cifar10.zip?si=cifar10&spr=https&sv=2021-06-08&sr=b&sig=d7lmXZ7SFF4ZWusbueK%2Bnssm%2BsskRXsovy2%2F5RBzylg%3D" 
filename = "cifar10.zip"
md5 = "c615b172eb42aac01f3a0737540944b1"

# WARNING: this will download and extract a 2.1GiB file, if not already present. Please save the file and avoid re-downloading it.
try:
    download_and_extract_archive(url=url, download_root=os.curdir, extract_root=None, filename=filename, md5=md5, remove_finished=False)
except urllib.error.HTTPError as e:
    print(e)
    print("Have you replaced the URL above with the one you got after registering?")

from torchcsprng import create_mt19937_generator, create_random_device_generator
from torch.utils.data import random_split

import os
import sys
import time

import numpy as np
import torch
import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim

from sklearn.model_selection import train_test_split
import csv

from tqdm.notebook import tqdm
device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")

def load_cifar10(dataset_dir, download=True):
    """Loads the CIFAR10 dataset.
    """
    from torchvision.datasets import CIFAR10
    import torchvision.transforms as transforms
    from torch.utils.data import ConcatDataset

    # Precomputed statistics of CIFAR10 dataset
    # Exact values are assumed to be known, but can be estimated with a modest privacy budget
    # Opacus wrongly uses CIFAR10_STD = (0.2023, 0.1994, 0.2010)
    # This is the _average_ std across all images (see https://github.com/kuangliu/pytorch-cifar/issues/8)
    CIFAR10_MEAN = (0.49139968, 0.48215841, 0.44653091)
    CIFAR10_STD  = (0.24703223, 0.24348513, 0.26158784)

    transform = transforms.Compose([
        transforms.ToTensor(),
        transforms.Normalize(CIFAR10_MEAN, CIFAR10_STD)
    ])

    # NB: torchvision checks the integrity of downloaded files
    train_dataset = CIFAR10(
        root=f"{dataset_dir}/cifar10",
        train=True,
        download=download,
        transform=transform
    )

    test_dataset = CIFAR10(
        root=f"{dataset_dir}/cifar10",
        train=False,
        download=download,
        transform=transform
    )

    return ConcatDataset([train_dataset, test_dataset])

def accuracy(preds: torch.Tensor, labels: torch.Tensor) -> float:
    return (preds == labels).mean()

# Architecture of shadow model
class ShadowNet(nn.Module):
    def __init__(self):
      super(ShadowNet, self).__init__()
      self.shadowCnn = nn.Sequential(
            nn.Conv2d(3, 128, kernel_size=8, stride=2, padding=3), nn.Tanh(),
            nn.MaxPool2d(kernel_size=3, stride=1),
            nn.Conv2d(128, 256, kernel_size=3), nn.Tanh(),
            nn.Conv2d(256, 256, kernel_size=3), nn.Tanh(),
            nn.AvgPool2d(kernel_size=2, stride=2),
            nn.Flatten(),
            nn.Linear(in_features=6400, out_features=10)
        )
    def forward(self, x):
      output = self.shadowCnn(x)
      return output

def get_gradients_and_loss(modelNum, inputs, targets):
  sCriterion = nn.CrossEntropyLoss()

  # load duplicate model
  loadedModel = ShadowNet()
  loadedModel.load_state_dict(torch.load(os.path.join(dirPath + "shadowModels/", "shadowModel"+str(modelNum)+".pt")))
  loadedModel = loadedModel.to(device)
  loadedModel.train()
  sOutput = loadedModel(inputs)
  sLoss = sCriterion(sOutput, targets)
  sPred = np.argmax(sOutput.detach().cpu().numpy(), axis=1)
  sLabel = targets.detach().cpu().numpy()
  acc = accuracy(sPred, sLabel)
  sLoss.backward()
  cnt = 0
  # print(sOutput)
  # print(sOutput.shape)
  # sOutput = torch.stack(sOutput, dim=0)
  grads = []
  # for output in sOutput:
    # grads.append(output)
  # grads.append(sOutput)
  
  for module in loadedModel.shadowCnn.children():
    if (cnt == 0 or cnt == 3 or cnt == 5 or cnt == 9):
      grads.append(module.weight.grad.detach().data.norm())
    cnt += 1
  grads.append(sLoss)
  sOutput = sOutput.detach().cpu().numpy()
  return sOutput, grads

def saveTargetDataset(model,traindataLoaderShader,testDataLoaderShader,data,modelNum):

  model.eval()
  sizeData = 500
  currentCount = 0
  saveFeatureTrain =True
  saveFeatureTest =True

  for j,(inputs, target) in enumerate(traindataLoaderShader):
    if saveFeatureTrain:
      inputs = inputs.to(device)
      target = target.to(device)

      features, grads_plus_loss = get_gradients_and_loss(modelNum, inputs, target)
      # grads_plus_loss = grads_plus_loss.detach().cpu().numpy()
      grads_plus_loss = [g.detach().cpu() for g in grads_plus_loss]
      grads_plus_loss = [g.numpy() for g in grads_plus_loss]
      # output = model(inputs)
      # features = output.detach().cpu().numpy()
      target = target.detach().cpu().numpy()
      # for count, feature in enumerate(features):
      if currentCount < sizeData:
        features = np.append(features, grads_plus_loss)
        features = np.append(features,1)
        features = np.append(features,target[0])
        data.append(features)
        currentCount+=1
      else:
        saveFeatureTrain = False
  currentCount = 0
  for j,(inputs, target) in enumerate(testDataLoaderShader):
    if saveFeatureTest:
      inputs = inputs.to(device)
      target = target.to(device)

      features, grads_plus_loss = get_gradients_and_loss(modelNum, inputs, target)
      # grads_plus_loss = grads_plus_loss.detach().cpu().numpy()
      grads_plus_loss = [g.detach().cpu() for g in grads_plus_loss]
      grads_plus_loss = [g.numpy() for g in grads_plus_loss]
      # output = model(inputs)
      # features = output.detach().cpu().numpy()
      target = target.detach().cpu().numpy()
      # for count, feature in enumerate(features):
      if currentCount < sizeData:
        features = np.append(features, grads_plus_loss)
        features = np.append(features,0)
        features = np.append(features,target[0])
        data.append(features)
        currentCount+=1
      else:
        saveFeatureest = False
  return data

# For infinity epsilon, no DP 
def trainShadowModels(nModel, shadowData,dirPath):
  sTrainingSize = 42000
  sTestingSize = 18000
  sEpochs = 50
  sBatchSize = 32
  sMaxGradNorm = 2.6
  sTargetEpsilon = 4.0
  sTargetDelta = 1/sTrainingSize
  sLR = 0.005
  sLrSchedulerGamma = 0.96

  seedGenerator = create_random_device_generator()
  for n in range(nModel):
    attackData = []
    sModel = ShadowNet()
    sModel = sModel.to(device)
    sCriterion = nn.CrossEntropyLoss()
    sOptimizer = optim.SGD(sModel.parameters(), lr=sLR, momentum=0)

    # generate a seed
    modelSeed = torch.empty(1, dtype=torch.int64).random_(0, to=None, generator=seedGenerator)
    # use the seed to create a generator
    generator = create_mt19937_generator(modelSeed)
    shadowTrainData, shadowTestData = random_split(shadowData, [sTrainingSize,sTestingSize], generator=generator)
    # shadowTrainData, shadowTestData = train_test_split(shadowData, test_size=0.3, random_state=42)
    traindataLoaderShader = torch.utils.data.DataLoader(shadowTrainData, batch_size=sBatchSize,shuffle = True, num_workers=4,pin_memory = True)
    saveTraindataLoaderShader = torch.utils.data.DataLoader(shadowTrainData, batch_size=1,shuffle = True, num_workers=4,pin_memory = True)
    testDataLoaderShader = torch.utils.data.DataLoader(shadowTestData, batch_size=500,shuffle = True, num_workers=4,pin_memory=True)
    saveTestdataLoaderShader = torch.utils.data.DataLoader(shadowTestData, batch_size=1,shuffle = True, num_workers=4,pin_memory = True)
    sScheduler = optim.lr_scheduler.StepLR(sOptimizer, step_size=1, 
                                          gamma=sLrSchedulerGamma)
    for i in range(sEpochs):

      sModel.train()

      sLosses = []
      sTop1Acc = []
      dataProcessed =0
      for j,(inputs, target) in enumerate(traindataLoaderShader):
        inputs = inputs.to(device)
        target = target.to(device)
        dataProcessed+=len(inputs)

        sOptimizer.zero_grad()
        sOutput = sModel(inputs)
        sLoss = sCriterion(sOutput, target)

        sPreds = np.argmax(sOutput.detach().cpu().numpy(), axis=1)
        sLabels = target.detach().cpu().numpy()
        acc = accuracy(sPreds, sLabels)

        sLosses.append(sLoss.item())
        sTop1Acc.append(acc)

        sLoss.backward()
        sOptimizer.step()

      sScheduler.step()

    modelName = "shadowModel"+str(n)+".pt"
    print("Saving shadow model ",modelName)
    torch.save(sModel.state_dict(), os.path.join(dirPath + "shadowModels/", modelName))
    # saving the seed
    filename = "seedShadowModel"+str(n)
    print( "file: ",filename)
    torch.save(modelSeed, os.path.join(dirPath + "shadowModels/", filename))
    # Get the attack dataset
    attackData = saveTargetDataset(sModel,saveTraindataLoaderShader,saveTestdataLoaderShader,attackData, n)
    # Test dataset results
    print("Test results:")
    testShadow(sModel,testDataLoaderShader,sCriterion)
    filename = "attackData"+str(n)+".csv"
    print( "file: ",filename)
    with open(os.path.join(dirPath + "attackData/", filename), "w", newline='') as f:
      for count, data in enumerate(attackData):
        csv.writer(f).writerow(data)


  return attackData

def testShadow(model,test_loader,criterion):
    model.eval()

    losses = []
    top1_acc = []

    with torch.no_grad():
        for inputs, target in tqdm(test_loader):
            inputs = inputs.to(device)
            target = target.to(device)

            output = model(inputs)
            loss = criterion(output, target)

            preds = np.argmax(output.detach().cpu().numpy(), axis=1)
            labels = target.detach().cpu().numpy()

            acc = accuracy(preds, labels)

            losses.append(loss.item())
            top1_acc.append(acc)

    top1_avg = np.mean(top1_acc)
    loss_avg = np.mean(losses)

    print(
        f"Test Loss    : {loss_avg:.6f}\n"
        f"Test Accuracy: {top1_avg * 100:.6f}"
    )

    return np.mean(top1_acc)

if __name__ == "__main__":

  # Data directory
  dataPath="cifar10/"
  if not os.path.isdir(dataPath):
    os.mkdir(dataPath)

  # Output directory
  dirPath="output/"
  if not os.path.isdir(dirPath):
    os.mkdir(dirPath)

  # Attack data directory
  if not os.path.isdir(dirPath+"attackData/"):
    os.mkdir(dirPath+"attackData/")
  else:
    os.rmdir(dirPath+"attackData/")
    os.mkdir(dirPath+"attackData/")

  # Shadow models directory
  if not os.path.isdir(dirPath+"shadowModels/"):
    os.mkdir(dirPath+"shadowModels/")
  else:
    os.rmdir(dirPath+"shadowModels/")
    os.mkdir(dirPath+"shadowModels/")

  dataset = load_cifar10(dataPath,download = True)
  print(len(dataset))
  # Train 500 shadow models
  attackData = trainShadowModels(500,dataset,dirPath)