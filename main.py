from pyspark.sql import SparkSession, DataFrame, Column
from pyspark.ml.feature import StandardScaler, VectorAssembler, PCA
from pyspark.ml.regression import LinearRegression
from pyspark.ml.evaluation import RegressionEvaluator
from pyspark.ml.tuning import CrossValidator, ParamGridBuilder

import pandas as pd
import numpy as np
import json

import matplotlib.pyplot as plt
import seaborn as sns
from matplotlib.lines import Line2D


class ClusterHandler():

    def __init__(self):
        self.data = None
        self.dataframe = None
        self.session = None


    def run_session(self, name:str = 'Session', type:str = 'local', ip:str = None, port:str = None, config:str = None) -> SparkSession.sparkContext:
        """
        Runs the spark session
        -----
        Args:
            * name: the name of the session.
            * type: 'local' or remote session. If 'remote', must provide IPv4 address and port number. 'local' is default.
            * ip [optional]: IPv4 address of the node.
            * port [optional]: port number of the node.
        -------
        Raises:
            * ValueError: if type is not 'local' or 'remote'.
        """

        type = type.lower()
        
        if type == "local":
            spark = SparkSession.builder \
                .appName(name) \
                .getOrCreate()
        
        elif type == "remote":
            if ip == None or port == None:
                raise ValueError("\033[31mMust provide 'ip' and 'port' in order to connect to remote node.\033[0m")
            
            spark = SparkSession.builder \
                .appName(name) \
                .master(f"spark://{ip}:{port}") \
                .getOrCreate()
            
        else:
            raise ValueError("\033[31mArgument 'type' must be 'local' or 'remote'.\033[0m")

        self.session = spark
        context = spark.sparkContext
        print(f"\nSession '{context.appName}' created on masternode {context.master}")
        print(f"Spark UI (jobs tab) is available at \033[36m{context.uiWebUrl}\033[0m\n")
        
        return context


    def generate_dataframe(self, data:pd.DataFrame, y:str = None):
        self.data = data
        if y:
            self.y = pd.DataFrame(data["critical_temp"])
            X = data.drop(columns=["critical_temp"])
            self.dataframe = self.session.createDataFrame(X)
        else:
            self.dataframe = self.session.createDataFrame(data)

    
    def assemble_features(self, assembler:VectorAssembler = None, input_columns:list = None, output_column:str = "features"):   
        if not assembler:
            if not input_columns:
                input_columns = list(self.dataframe.columns[0:])
            assembler = VectorAssembler(inputCols=input_columns, outputCol=output_column)
        self.dataframe = assembler.transform(self.dataframe)


    def scale_features(self, scaler:StandardScaler = None, input_column:str = "features", output_column:str = "scaledFeatures"):
        if not scaler:
            scaler = StandardScaler(inputCol=input_column, outputCol=output_column, withStd=True, withMean=True)
        self.dataframe = scaler.fit(self.dataframe).transform(self.dataframe)


    def fit_pca(self, model:PCA):
        self.pca_model = model.fit(self.dataframe)
        self.pca_result = self.pca_model.transform(self.dataframe)
        self.pca_coefficients = self.pca_model.pc.toArray()
        

    def extract_pca_coefficients(self, dimension:int):
        feat_coeff = {feature: coefficient[dimension] for feature, coefficient in zip(self.dataframe.columns, self.pca_coefficients)}
        return dict(sorted(feat_coeff.items(), key=lambda x: abs(x[1]), reverse=True))


    def fit_lr(self, model:LinearRegression, y_column:str, pred_column:str = "prediction", folds:int = 5, reg_params:list = [0.01, 0.05, 1.0]):
        
        param_grid = ParamGridBuilder() \
                    .addGrid(model.regParam, reg_params) \
                    .build()
        
        evaluator = RegressionEvaluator(predictionCol=pred_column, labelCol=y_column, metricName="r2")
        cross_validator = CrossValidator(estimator=model, estimatorParamMaps=param_grid, evaluator=evaluator, numFolds=folds)

        cv_model = cross_validator.fit(self.dataframe)
        self.lr_model = cv_model.bestModel
        self.lr_coefficients = list(self.lr_model.coefficients)

        return {fold: r2 for fold, r2 in zip(reg_params, cv_model.avgMetrics)}
        

    def extract_lr_coefficients(self):
        feat_coeff = {feature: coefficient for feature, coefficient in zip(self.dataframe.columns, self.lr_coefficients)}
        return dict(sorted(feat_coeff.items(), key=lambda x: abs(x[1]), reverse=True))
    

    def plot_3d_pca(self, dimensions=list, color_by:str = None):

        pca_result_sub = self.pca_result.select("pcaFeatures").collect()
        pca_values = [tuple(row.pcaFeatures.toArray()) for row in pca_result_sub]
        pca_transposed = list(zip(*pca_values))

        if len(dimensions) != 3:
            raise ValueError("\033[31mMust provide 3 dimensions to plot.\033[0m")

        fig = plt.figure(figsize=(10, 7))
        ax = fig.add_subplot(111, projection='3d')
        
        ax.set_xlabel(f'Dimension {dimensions[0]}')
        ax.set_ylabel(f'Dimension {dimensions[1]}')
        ax.set_zlabel(f'Dimension {dimensions[2]}')
        ax.set_title(f'3D PCA scatter for dimensions {dimensions[0]}, {dimensions[1]}, {dimensions[2]}', color="white")

        if color_by:
            color_feature = self.data[color_by].to_numpy()
            ax.scatter(xs=pca_transposed[dimensions[0]], ys=pca_transposed[dimensions[1]], zs=pca_transposed[dimensions[2]],
                       c=color_feature, cmap="rocket", s=2, alpha=0.6)
            
            legend_elements = [
                Line2D([0], [0], marker='o', color='w', markerfacecolor='#f5c5ac', markersize=10, label='Low'),
                Line2D([0], [0], marker='o', color='w', markerfacecolor='#c6004e', markersize=10, label='Medium'),
                Line2D([0], [0], marker='o', color='w', markerfacecolor='#251432', markersize=10, label='High')
            ]

        
            legend = ax.legend(handles=legend_elements, title=color_by, loc='upper left', labels=['Low', 'Medium', 'High'])
            for text in legend.get_texts():
                text.set_color('white')
            legend.get_title().set_color('white')
            legend.get_title().set_weight('bold')
        
        else:
            ax.scatter(xs=pca_transposed[dimensions[0]], ys=pca_transposed[dimensions[1]], zs=pca_transposed[dimensions[2]],
                       s=2, alpha=0.6, color="orange")



def load_sns_theme(theme_path: str, apply:bool = True) -> json:
    """
    Loads the Seaborn/Matplolib theme from a json file
    -----
    Args:
        * theme_path: path of the json file
        * apply: applies the theme to Seaborn if True
    --------
    Returns:
        * A json formatted file
    """

    with open(theme_path) as file:
        theme = json.load(file)
        file.close()
    
    if apply is True:
        sns.set_style("dark", rc=theme)
    
    return theme



if __name__ == "__main__":

    # Quick example with PCA model and local server
    data = pd.read_csv("data/superconductivity.csv")
    y = pd.DataFrame(data["critical_temp"])
    X = data.drop(columns=["critical_temp"])
    
    handler = ClusterHandler(X)
    handler.run_session()
    handler.generate_dataframe()

    handler.assemble_features()
    handler.scale_features()

    pca = PCA(k=5, inputCol="scaledFeatures", outputCol="pcaFeatures")
    pca_result = handler.fit_pca(pca)
    pca_result.show()

    print(handler.extract_pca_coefficients(model=pca, dimension=0))

    handler.session.stop()