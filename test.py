# -*- coding: utf-8 -*-
"""
Created on Sun Mar 24 14:43:57 2019

@author: Qi Wang
"""

from pyspark.sql import SparkSession
import numpy as np

spark = SparkSession.builder.getOrCreate()
sc = spark.sparkContext

import pyspark
from pyspark.ml import feature, regression, Pipeline
from pyspark.sql import functions as fn, Row
from pyspark import sql
from pyspark.ml.regression import LinearRegression
from pyspark.ml.evaluation import RegressionEvaluator
from pyspark.ml.classification import LogisticRegression

import matplotlib.pyplot as plt
import pandas as pd


##############################################################################
##########       Spark creat and transform data             #################
##############################################################################
## Spark Method ##
Full_data = spark.read.csv('train_V2.csv', sep=',', inferSchema=True, header=True)
# seperate match type
update_fun = (fn.when(fn.col('matchType').contains('solo'), 'solo').when(fn.col('matchType').contains('duo' or 'crash'), 'duo')
                .otherwise('squad'))
Full_data = Full_data.withColumn('matchType', update_fun)
##############################################################################
###### collect solo match
New_df_solo = Full_data.filter(Full_data.matchType == 'solo')
columns = ['Id','groupId','matchId','matchType']
New_df_solo = New_df_solo.select([col for col in New_df_solo.columns if col not in columns])
pj_sp_df_solo = New_df_solo.sample(withReplacement=False, fraction=0.1, seed=3)
##############################################################################
###### collect team match
New_df_team  = Full_data.select('*').groupby('groupId').agg(fn.sum('damageDealt').alias('total_team_damage'),
                      fn.sum('kills').alias('total_team_kills'),
                      fn.sum('killPoints').alias('team_kill_points'),
                      fn.avg('killPlace').alias('team_kill_rank'),
                      fn.avg('rankPoints').alias('team_normal_rank'),
                      fn.sum('revives').alias('team_revives'),
                      fn.sum('boosts').alias('team_boosts'),
                      fn.sum('assists').alias('total_assists'),
                      fn.sum('DBNOs').alias('team_DBNOs'),
                      fn.sum(Full_data.rideDistance + Full_data.walkDistance + Full_data.swimDistance).alias('totalDistance'))
New_df_team  = New_df_team.join(Full_data,New_df_team .groupId == Full_data.groupId)


##
columns = ['Id','groupId','matchId', 'roadKills','numGroups','rideDistance','walkDistance','swimDistance','kills','killPints','killPlace','rankPoints','revives','boosts','assists','DBNOs']
New_df_team = New_df_team.select([col for col in New_df_team.columns if col not in columns])

################################################################################
pj_sp_df_team = New_df_team.sample(withReplacement=False, fraction=0.1, seed=3)
##
#withColumn('solo',(fn.col('matchType') == 'solo').cast('int')).\
pj_sp_df_team = pj_sp_df_team.\
                    withColumn('duo',(fn.col('matchType') == 'duo').cast('int')).\
                    withColumn('squad',(fn.col('matchType') == 'squad').cast('int'))
pj_sp_df_team = pj_sp_df_team.drop('matchType')
pj_sp_df_team.show(5)
##############################################################################


#####################################################################
###############         Model Part       #############           
#####################################################################
#### Build a PCA Class
class PCA:
    def __init__(self,df):
        self.df = df
        self.inputcol = self.df.columns
        self.inputcol.remove('winPlacePerc')
    
    def Pipe_line(self,k):
         self.pipeline_PCA = Pipeline(stages=[
                            feature.VectorAssembler(inputCols=self.inputcol,outputCol='features'),
                            feature.StandardScaler(withMean=True,inputCol='features', outputCol='zfeatures'),
                            feature.PCA(k=k, inputCol='zfeatures', outputCol='loadings')
                            ]).fit(self.df)
         return self.pipeline_PCA
     
    def PC(self):
        self.principal_components = self.pipeline_PCA.stages[-1].pc.toArray()
        self.pca_model = self.pipeline_PCA.stages[-1]
        self.explainedVariance = self.pca_model.explainedVariance
        return {'PC':self.principal_components,"Model":self.pca_model,"EV":self.explainedVariance}
    
    def choose(self,th = 0.98):
        for i in range(0,1000):
             if self.explainedVariance[i] < 0.01:
                break
        print ('best k = ', i-1)
        self.sumEV = 0
        for i in range(0,1000):
             self.sumEV += self.explainedVariance[i]
             if self.sumEV > th:
                    break
        print ('best k = ', i-1)     
        plt.plot(np.cumsum(self.explainedVariance))
        plt.xlabel('number of components')
        plt.ylabel('cumulative explained variance')
    
    def Print_first2(self):
        pc1_pd =pd.DataFrame({'Feature': self.inputcol, 'abs_loading': abs(self.principal_components[:,0])}).sort_values('abs_loading',ascending=False)
        pc2_pd =pd.DataFrame({'Feature': self.inputcol, 'abs_loading': abs(self.principal_components[:,1])}).sort_values('abs_loading',ascending=False)
        return {'pc1':pc1_pd,'pc2':pc2_pd}
    
    def reduced_dm(self,n):
        PCA_choosed = self.principal_components[:,:n]
        tpdf = self.df.drop('winPlacePerc')
        sp_np = tpdf.toPandas().values
        pc_df_solo = np.dot(sp_np,PCA_choosed)
        pc_df_solo =pd.DataFrame(pc_df_solo)
        return pc_df_solo
        
##########################################################      
##########    PCA  (solo)      #################### 
solo_model = PCA(pj_sp_df_solo)
solo_model.Pipe_line(20)
solo_model.PC()
solo_model.choose()
##########         PC Results first two dimension
pc1_pd = solo_model.Print_first2()['pc1']
pc2_pd = solo_model.Print_first2()['pc2']
##############      Reduced Dimension      #############################
pc_df_solo = solo_model.reduced_dm(15)
pc_df_solo.describe()
##########################################################  

##########    PCA  (team)      #################### 
team_model = PCA(pj_sp_df_team)
team_model.Pipe_line(20)
team_model.PC()
team_model.choose()
##########         PC Results first two dimension
pc1_pd = team_model.Print_first2()['pc1']
pc2_pd = team_model.Print_first2()['pc2']
##############      Reduced Dimension      #############################
pc_df_team = team_model.reduced_dm(16)
pc_df_team.describe()
########################################################## 
########################################################## 
## Linear with Origin
# RMSE Function
rmse = fn.sqrt(fn.mean((fn.col('winPlacePerc')-fn.col('prediction'))**2)).alias("rmse")   
def rmseLr(alpha, beta, fit_df, transform_df, test_df,maxiter = 100):
    lr =  LinearRegression().\
        setLabelCol('winPlacePerc').\
        setFeaturesCol('scaledFeatures').\
        setRegParam(beta).\
        setMaxIter(maxiter).\
        setElasticNetParam(alpha)

    pipe_Lr_og = Pipeline(stages = [
      feature.VectorAssembler(inputCols = inputcol ,outputCol = 'feature'),
      feature.StandardScaler(withMean=True,inputCol="feature", outputCol="scaledFeatures"),
      lr]).fit(fit_df)

    coeff = pipe_Lr_og.stages[2].coefficients.toArray()
    coeffs_df = pd.DataFrame({'Features': inputcol, 'Coeffs': abs(coeff)})
    coeffs_df.sort_values('Coeffs', ascending=False)
    
    ## rmse of validationdata
    print('RMSE of Validation Data Set')
    rmse3_df = pipe_Lr_og.transform(transform_df).select(rmse)
    
    ## Summary of testing data
    train_summary = pipe_Lr_og.stages[-1].summary
    print("Training RMSE: %f" % train_summary.rootMeanSquaredError)
    print("Trainingr2: %f" % train_summary.r2)
    
    lr_predictions = pipe_Lr_og.transform(test_df)
    lr_evaluator = RegressionEvaluator(predictionCol="prediction", \
                 labelCol="winPlacePerc",metricName="r2")
    
    print("R Squared (R2) on test data = %g" % lr_evaluator.evaluate(lr_predictions))
    
    return {'rmse':rmse3_df.show(),'pipe_model':pipe_Lr_og,'Train_su': train_summary,'Test_model':lr_predictions}

############################################################################3
def runModel():
    n = 0
    for i in np.arange(0,1.1,0.1):
       if i == 0 or i == 1:
          for j in np.arange(0,0.2,0.1):
            n+=1
            print('Model:',n,'Alpha:',i,"Lambda: ",j)
            rmseLr(i,j,training_df, validation_df, testing_df)
       else:
           j = 0.1
           n+=1
           print('Model:',n,'Alpha:',i,"Lambda: ",j)
           rmseLr(i,j,training_df, validation_df, testing_df)

############################################################################3
##########     Linear Model of Team  Original Data  ############
training_df, validation_df, testing_df = pj_sp_df_team.randomSplit([0.6, 0.3, 0.1], seed=0)
inputcol = pj_sp_df_team.columns
inputcol.remove('winPlacePerc')
##########       Model  Out put
runModel()
############ Model is the best             ########################
#         Model: 1 Alpha: 0.0 Lambda:  0.0
#             RMSE of Validation Data Set
#             Training RMSE: 0.129407
#             Trainingr2: 0.822858
#             R Squared (R2) on test data = 0.824897
#             +-------------------+
#             |               rmse|
#             +-------------------+
#             |0.12931329250256463|
#             +-------------------+
################################################################
        
##########     Linear Model of solo  Original Data  ############
training_df, validation_df, testing_df = pj_sp_df_solo.randomSplit([0.6, 0.3, 0.1], seed=0)
inputcol = pj_sp_df_solo.columns
inputcol.remove('winPlacePerc')
##########       Model  Out put
runModel()
############ Model is the best             ########################
#         Model: 1 Alpha: 0.0 Lambda:  0.0
#           RMSE of Validation Data Set
#           Training RMSE: 0.104621
#           Trainingr2: 0.877490
#           R Squared (R2) on test data = 0.87965
#           +-------------------+
#           |               rmse|
#           +-------------------+
#           |0.10608384409927706|
#           +-------------------+
################################################################
#############       PCA Linear Model     ###################
pc_sp_df_team = spark.createDataFrame(pc_df_team)
pc_sp_df_team.withColumn('winPlacePerc',pj_sp_df_team['winPlacePerc'])

#############################################################
#Combine pc dataframe with column 'winPlacePerc'
def combinedf(pc_df, pj_sp_df):
    pc_df1 =  spark.createDataFrame(pc_df)
    pc_df1=pc_df1.withColumn('index',fn.monotonically_increasing_id())
    pj_sp_df1 = pj_sp_df.select('winPlacePerc').withColumn('index',fn.monotonically_increasing_id())
    join_df = pc_df1.join(pj_sp_df1, on=['index'])
    return(join_df)
##############################################################
##########     Linear Model of Solo  PCA Data  ############
##########       Model  Out put
join_pc_df_solo = combinedf(pc_df_solo,pj_sp_df_solo)
inputcol = list(join_pc_df_solo.columns)
inputcol.remove('winPlacePerc')
inputcol.remove('index')
training_df, validation_df, testing_df = join_pc_df_solo.randomSplit([0.6, 0.3, 0.1], seed=0)
##############################################################
runModel()     
##############################################################
##########     Linear Model of Team  PCA Data  ############
##########       Model  Out put
join_pc_df_team = combinedf(pc_df_team,pj_sp_df_team)
inputcol = list(join_pc_df_team.columns)
inputcol.remove('winPlacePerc')
inputcol.remove('index')
training_df, validation_df, testing_df = join_pc_df_team.randomSplit([0.6, 0.3, 0.1], seed=0)
##########       Model  Out put
runModel()


##############################################################
#Logit
##############################################################
#split the data set into five categories in 

splits = [ float("-inf"), 0.1, 0.2, 0.3,0.4,0.5,0.6,0.7,0.8,0.9, float('Inf') ]
from pyspark.ml.feature import Bucketizer
bucketizer = Bucketizer(splits=splits ,inputCol='winPlacePerc', outputCol='rank')
pj_lg_df_solo = bucketizer.setHandleInvalid("keep").transform(pj_sp_df_solo).drop('winPlacePerc')
pj_lg_df_team = bucketizer.setHandleInvalid("keep").transform(pj_sp_df_team).drop('winPlacePerc')

from pyspark.ml.evaluation import MulticlassClassificationEvaluator
#####################################################################
#### Ordinarl logistic regression Model
training_df, validation_df, testing_df = pj_lg_df_team.randomSplit([0.6, 0.3, 0.1], seed=0)
def logitReg(reg,elastic,training,validate):
    inputcol = training_df.columns
    inputcol.remove('rank')
    logitReg = LogisticRegression().\
        setMaxIter(100).\
        setLabelCol('rank').\
        setFeaturesCol('scaledFeatures').\
        setRegParam(reg).\
        setElasticNetParam(elastic)

    pipe_log=Pipeline(stages=[
        feature.VectorAssembler(inputCols=inputcol, outputCol='features'),
        feature.StandardScaler(withMean=True, inputCol='features', outputCol='scaledFeatures'),
        logitReg
        ]).fit(training)
#    logSummary = pipe_log.stages[-1].summary
#    accuracy = logSummary.accuracy
#    falsePositiveRate = logSummary.weightedFalsePositiveRate
#    truePositiveRate = logSummary.weightedTruePositiveRate
#    fMeasure = logSummary.weightedFMeasure()
#    precision = logSummary.weightedPrecision
#    recall = logSummary.weightedRecall
#    print("Accuracy: %s\nFPR: %s\nTPR: %s\nF-measure: %s\nPrecision: %s\nRecall: %s"   % (accuracy, falsePositiveRate, truePositiveRate, fMeasure, precision, recall))
    predictions = pipe_log.transform(validate)
    evaluator = MulticlassClassificationEvaluator(labelCol="rank", predictionCol="prediction", metricName="accuracy")
    accuracy = evaluator.evaluate(predictions)
    print("Test Error = %g" % (1.0 - accuracy),"Accuracy = %g" % (accuracy))
##################################################
###################    
def runLgModel():
    n = 0
    for i in np.arange(0,1.1,0.1):
       if i == 0 or i == 1:
          for j in np.arange(0,0.2,0.1):
            n+=1
            print('Model:',n,'Alpha:',i,"Lambda: ",j)
            logitReg(i,j,training_df, validation_df)
       else:
           j = 0.1
           n+=1
           print('Model:',n,'Alpha:',i,"Lambda: ",j)
           logitReg(i,j,training_df, validation_df)
###################  
runLgModel()
#####################################################################
training_df, validation_df, testing_df = pj_lg_df_solo.randomSplit([0.6, 0.3, 0.1], seed=0)
###################  
runLgModel()